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
    secrets = list(
        session.scalars(
            select(CredentialSecret).where(CredentialSecret.key_version != target_version)
        ).all()
    )
    rewrapped = 0
    for secret in secrets:
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


def _count_old_blob_files(root: Path, target_version: int, errors: list[str]) -> int:
    remaining = 0
    for path in sorted(root.rglob("*.blob")):
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
    tmp = path.with_suffix(path.suffix + ".rewrap")
    try:
        with path.open("rb") as src, tmp.open("wb") as dst:
            for piece in iter_wrap(iter_unwrap(src, keyring=keyring), keyring=keyring, key_version=target):
                dst.write(piece)
            dst.flush()
            os.fsync(dst.fileno())
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
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
    paths = sorted(root.rglob("*.blob"))
    if limit is not None:
        paths = paths[:limit]

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

    for path in paths:
        scanned += 1
        try:
            changed, ver = rewrap_blob_file(path, keyring=keyring, target_version=target)
            if changed:
                rewritten += 1
            else:
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
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
            log.warning("rewrap failed for %s: %s", path, exc)

    remaining_old_blobs = _count_old_blob_files(root, target, errors)
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
