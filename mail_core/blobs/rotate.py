"""Blob key rotation: decrypt with old version, re-wrap with active key (architecture §11).

Crash safety: each file is rewritten via fsync + atomic replace, then that digest's
``MessageBlob.key_version`` is committed before the next file. A crash leaves at most
one digest with file/DB temporarily divergent; the on-disk KKMS header is authoritative
and the next rotate pass re-syncs the row.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.blobs.archive import blob_root
from mail_core.blobs.crypto import Keyring, iter_unwrap, iter_wrap, load_keyring_from_env, read_key_version
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import MessageBlob

log = logging.getLogger("mail_core.blobs.rotate")


@dataclass(frozen=True, slots=True)
class RewrapResult:
    scanned: int
    rewritten: int
    already_current: int
    errors: list[str]


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
    """Walk blob store; after each successful rewrite, commit that digest's key_version."""
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

    return RewrapResult(scanned=scanned, rewritten=rewritten, already_current=already, errors=errors)


def run_rewrap(*, target_version: int | None = None, limit: int | None = None) -> dict:
    result = rewrap_all_blobs(target_version=target_version, limit=limit)
    return {
        "scanned": result.scanned,
        "rewritten": result.rewritten,
        "already_current": result.already_current,
        "errors": result.errors,
    }
