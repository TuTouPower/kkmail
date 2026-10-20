"""Blob key rotation: decrypt with old version, re-wrap with active key (architecture §11)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.blobs.archive import blob_root
from mail_core.blobs.crypto import Keyring, iter_unwrap, iter_wrap, load_keyring_from_env, read_key_version
from mail_core.blobs.store import BlobStore
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
    with path.open("rb") as src, tmp.open("wb") as dst:
        for piece in iter_wrap(iter_unwrap(src, keyring=keyring), keyring=keyring, key_version=target):
            dst.write(piece)
        dst.flush()
        os.fsync(dst.fileno())
    tmp.replace(path)
    return True, target


def rewrap_all_blobs(
    *,
    root: Path | None = None,
    keyring: Keyring | None = None,
    target_version: int | None = None,
    session: Session | None = None,
    limit: int | None = None,
) -> RewrapResult:
    """Walk blob store (and optionally sync MessageBlob.key_version)."""
    keyring = keyring or load_keyring_from_env()
    target = target_version if target_version is not None else keyring.active_version
    root = Path(root or blob_root())
    scanned = rewritten = already = 0
    errors: list[str] = []
    paths = sorted(root.rglob("*.blob"))
    if limit is not None:
        paths = paths[:limit]
    digest_versions: dict[str, int] = {}
    for path in paths:
        scanned += 1
        try:
            changed, ver = rewrap_blob_file(path, keyring=keyring, target_version=target)
            if changed:
                rewritten += 1
            else:
                already += 1
            # path .../ab/cd/<sha256>.blob
            digest = path.stem
            if len(digest) == 64:
                digest_versions[digest] = ver
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{path}: {type(exc).__name__}: {exc}")
            log.warning("rewrap failed for %s: %s", path, exc)

    own_session = session is None
    if digest_versions:
        Session = get_session_factory() if own_session else None
        sess = session or Session()
        try:
            for digest, ver in digest_versions.items():
                rows = list(sess.scalars(select(MessageBlob).where(MessageBlob.content_sha256 == digest)))
                for row in rows:
                    if int(row.key_version) != ver:
                        row.key_version = ver
            if own_session:
                sess.commit()
            else:
                sess.flush()
        finally:
            if own_session and session is None:
                sess.close()

    return RewrapResult(scanned=scanned, rewritten=rewritten, already_current=already, errors=errors)


def run_rewrap(*, target_version: int | None = None, limit: int | None = None) -> dict:
    result = rewrap_all_blobs(target_version=target_version, limit=limit)
    return {
        "scanned": result.scanned,
        "rewritten": result.rewritten,
        "already_current": result.already_current,
        "errors": result.errors,
    }
