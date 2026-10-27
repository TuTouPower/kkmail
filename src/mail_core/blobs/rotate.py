"""Blob key rotation: decrypt with old version, re-wrap with active key (architecture §11).

Crash safety: each file is rewritten via fsync + atomic replace. When running with internal
sessions (session=None), that digest's ``MessageBlob.key_version`` is committed before the
next file. Credential secrets are rewrapped only after all blob files reach the target
version without errors. When an external session is passed, database changes are flushed
without committing, leaving transaction boundaries to the caller. The result marks old
keys safe to retire only after committed credential migration and zero remaining old-version
blob files and credential rows.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from mail_core.blobs.archive import blob_root
from mail_core.blobs.crypto import Keyring, iter_unwrap, iter_wrap, load_keyring_from_env, read_key_version
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import CredentialSecret, MessageBlob

log = logging.getLogger("mail_core.blobs.rotate")

_CRED_HKDF_INFO = b"kkmail/credential-store/v1"


def _cred_key(keyring: Keyring, version: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_CRED_HKDF_INFO).derive(
        keyring.get(version)
    )


def _rewrap_credential_secrets(session: Session, keyring: Keyring, target_version: int) -> int:
    from mail_core.accounts.credentials import credential_lock_key

    candidate_refs = list(
        session.scalars(
            select(CredentialSecret.ref)
            .where(CredentialSecret.key_version != target_version)
            .order_by(CredentialSecret.ref)
        ).all()
    )
    is_postgres = session.get_bind().dialect.name == "postgresql"
    rewrapped = 0
    for ref in candidate_refs:
        # Join the credential_edit lock protocol (R03): take the per-ref
        # advisory lock, then re-read the row FOR UPDATE so a refresh/edit
        # that committed after the candidate scan is rewrapped from its
        # latest ciphertext instead of being overwritten by a stale snapshot.
        if is_postgres:
            session.execute(select(func.pg_advisory_xact_lock(credential_lock_key(ref))))
        secret = session.scalars(
            select(CredentialSecret)
            .where(CredentialSecret.ref == ref)
            .with_for_update()
            .execution_options(populate_existing=True)
        ).first()
        if secret is None or secret.key_version == target_version:
            continue
        old_k = _cred_key(keyring, secret.key_version)
        pt = AESGCM(old_k).decrypt(secret.nonce, secret.ciphertext, secret.ref.encode())
        new_k = _cred_key(keyring, target_version)
        new_nonce = os.urandom(12)
        new_ct = AESGCM(new_k).encrypt(new_nonce, pt, secret.ref.encode())
        secret.key_version = target_version
        secret.nonce = new_nonce
        secret.ciphertext = new_ct
        rewrapped += 1
    session.flush()
    return rewrapped


def _count_old_credential_secrets(session: Session, target_version: int) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(CredentialSecret)
            .where(CredentialSecret.key_version != target_version)
        )
        or 0
    )


def _count_old_blob_files(paths: list[Path], target_version: int, errors: list[str]) -> int:
    """Count old-version files among an explicit candidate set.

    Only failed or unreadable files are rechecked here; files the main scan
    already classified are never reopened (A288).
    """
    remaining = 0
    for path in sorted(paths):
        try:
            with path.open("rb") as fh:
                version = read_key_version(fh)
        except Exception as exc:  # noqa: BLE001
            error = f"{path}: {type(exc).__name__}: {exc}"
            if error not in errors:
                errors.append(error)
            log.warning("could not verify blob key version for %s: %s", path, exc)
            continue
        if version != target_version:
            remaining += 1
    return remaining


@dataclass(frozen=True, slots=True)
class RewrapResult:
    scanned: int
    rewritten: int
    already_current: int
    errors: list[str]
    remaining_old_version_blobs: int = 0
    remaining_old_version_credentials: int | None = None
    credential_secrets_rewrapped: int = 0
    credential_secrets_committed: bool = False

    @property
    def safe_to_retire_old_keys(self) -> bool:
        return (
            not self.errors
            and self.remaining_old_version_blobs == 0
            and self.remaining_old_version_credentials == 0
            and self.credential_secrets_committed
        )


def _fsync_parent_dir(path: Path) -> None:
    """fsync the directory holding ``path`` so a rename is durable."""
    try:
        fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def rewrap_blob_file(
    path: Path,
    *,
    keyring: Keyring,
    target_version: int | None = None,
) -> tuple[bool, int]:
    """Re-encrypt one on-disk blob. Returns (rewritten, new_or_old_version)."""
    target = target_version if target_version is not None else keyring.active_version
    with path.open("rb") as fh:
        old_ver = read_key_version(fh)
    if old_ver == target:
        return False, old_ver
    tmp = path.with_name(f"{path.name}.rewrap-{uuid.uuid4().hex}")
    created = False
    try:
        # Temp file holds decrypted-then-rewrapped key material in flight:
        # create it owner-only (0o600) instead of the umask default.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
        try:
            os.fchmod(fd, 0o600)
        except (AttributeError, OSError):
            pass
        with path.open("rb") as src, os.fdopen(fd, "wb") as dst:
            for piece in iter_wrap(iter_unwrap(src, keyring=keyring), keyring=keyring, key_version=target):
                dst.write(piece)
            dst.flush()
            os.fsync(dst.fileno())
        tmp.replace(path)
        _fsync_parent_dir(path)
    finally:
        if created:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
    return True, target


def _sync_key_version(session: Session, digest: str, ver: int) -> None:
    rows = list(session.scalars(select(MessageBlob).where(MessageBlob.content_sha256 == digest)))
    for row in rows:
        if int(row.key_version) != ver:
            row.key_version = ver
    session.flush()


def rewrap_all_blobs(
    *,
    root: Path | None = None,
    keyring: Keyring | None = None,
    target_version: int | None = None,
    session: Session | None = None,
    limit: int | None = None,
) -> RewrapResult:
    """Walk blob store and re-encrypt files to target_version.

    When ``session`` is None, commits each digest's updated key_version after each
    file rewrite. When an external ``session`` is provided, flushes changes without
    committing so the caller controls the transaction boundary.
    """
    keyring = keyring or load_keyring_from_env()
    target = target_version if target_version is not None else keyring.active_version
    root = Path(root or blob_root())
    scanned = rewritten = already = 0
    errors: list[str] = []
    paths: list[Path] = []
    current_paths: list[Path] = []
    scan_error_paths: list[Path] = []
    scan_errors = 0
    for path in sorted(root.rglob("*.blob")):
        try:
            with path.open("rb") as fh:
                version = read_key_version(fh)
        except Exception as exc:  # noqa: BLE001
            scan_errors += 1
            scan_error_paths.append(path)
            error = f"{path}: {type(exc).__name__}: {exc}"
            if error not in errors:
                errors.append(error)
            log.warning("could not inspect blob key version for %s: %s", path, exc)
            continue
        if version == target:
            already += 1
            current_paths.append(path)
        else:
            paths.append(path)
    truncated_paths: list[Path] = []
    if limit is not None:
        truncated_paths = paths[limit:]
        paths = paths[:limit]
    scanned = already + scan_errors + len(paths)
    # Current files bypass the rewrite limit but still repair DB metadata after a crash.
    paths = current_paths + paths
    current_path_set = set(current_paths)

    own_session = session is None
    db_sync = True
    SessionFactory = None
    if own_session:
        if not os.environ.get("MAIL_CORE_DATABASE_URL"):
            db_sync = False
        else:
            try:
                SessionFactory = get_session_factory()
            except Exception as exc:  # noqa: BLE001
                log.warning("rewrap DB sync disabled: %s", exc)
                db_sync = False

    failed_paths: list[Path] = []
    for path in paths:
        try:
            changed, ver = rewrap_blob_file(path, keyring=keyring, target_version=target)
            if changed:
                rewritten += 1
            elif path not in current_path_set:
                already += 1
            digest = path.stem
            if len(digest) != 64:
                continue
            # Crash-atomic: persist key_version for this digest before touching the next file.
            if not db_sync:
                continue
            if own_session:
                with SessionFactory() as sess:
                    _sync_key_version(sess, digest, ver)
                    sess.commit()
            else:
                assert session is not None
                _sync_key_version(session, digest, ver)
        except Exception as exc:  # noqa: BLE001
            failed_paths.append(path)
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
            log.warning("rewrap failed for %s: %s", path, exc)

    # A288: derive the remaining count from the scan tallies instead of a
    # second full-tree rglob + header read of every file. Old files skipped
    # by ``limit`` are still old by construction; only failed rewrites and
    # files the scan could not read need a targeted recheck.
    remaining_old_blobs = len(truncated_paths) + _count_old_blob_files(
        failed_paths + scan_error_paths, target, errors
    )
    credential_secrets_rewrapped = 0
    credential_secrets_committed = False
    if db_sync and not errors and remaining_old_blobs == 0:
        try:
            if own_session:
                with SessionFactory() as sess:
                    credential_secrets_rewrapped = _rewrap_credential_secrets(sess, keyring, target)
                    sess.commit()
                credential_secrets_committed = True
            else:
                assert session is not None
                credential_secrets_rewrapped = _rewrap_credential_secrets(session, keyring, target)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"credential_secrets: {type(exc).__name__}: {exc}")
            log.warning("rewrap credential secrets failed: %s", exc)

    remaining_old_credentials: int | None = None
    if db_sync:
        try:
            if own_session:
                with SessionFactory() as sess:
                    remaining_old_credentials = _count_old_credential_secrets(sess, target)
            else:
                assert session is not None
                remaining_old_credentials = _count_old_credential_secrets(session, target)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"credential_secrets verification: {type(exc).__name__}: {exc}")
            log.warning("could not verify credential key versions: %s", exc)

    return RewrapResult(
        scanned=scanned,
        rewritten=rewritten,
        already_current=already,
        errors=errors,
        remaining_old_version_blobs=remaining_old_blobs,
        remaining_old_version_credentials=remaining_old_credentials,
        credential_secrets_rewrapped=credential_secrets_rewrapped,
        credential_secrets_committed=credential_secrets_committed,
    )


def run_rewrap(*, target_version: int | None = None, limit: int | None = None) -> dict:
    result = rewrap_all_blobs(target_version=target_version, limit=limit)
    return {
        "scanned": result.scanned,
        "rewritten": result.rewritten,
        "already_current": result.already_current,
        "errors": result.errors,
        "remaining_old_version_blobs": result.remaining_old_version_blobs,
        "remaining_old_version_credentials": result.remaining_old_version_credentials,
        "credential_secrets_rewrapped": result.credential_secrets_rewrapped,
        "safe_to_retire_old_keys": result.safe_to_retire_old_keys,
    }
