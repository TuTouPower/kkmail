"""Delayed blob GC (architecture §10.2).

Cool-off is measured from ``gc_eligible_at`` (when ref_count hit 0), not
``created_at``. Deletion is two-phase: DB rows are removed and committed first;
on-disk unlinks happen only after that commit so a crash cannot leave a live
row pointing at a missing file.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mail_core.blobs.archive import blob_root
from mail_core.mail.storage.models import MessageBlob, MessageBlobLink

log = logging.getLogger("mail_core.blobs.gc")


@dataclass(frozen=True, slots=True)
class GcResult:
    marked: int
    deleted: int
    skipped_cooloff: int
    paths_to_unlink: tuple[Path, ...] = ()


def mark_unreferenced_blobs(session: Session, *, now: datetime | None = None) -> int:
    """Reconcile ref_count from links; stamp/clear ``gc_eligible_at``."""
    now = now or datetime.now(timezone.utc)
    blobs = list(session.scalars(select(MessageBlob)).all())
    marked = 0
    for blob in blobs:
        n = session.scalar(
            select(func.count()).select_from(MessageBlobLink).where(MessageBlobLink.blob_id == blob.id)
        ) or 0
        n = int(n)
        prev = int(blob.ref_count)
        if prev != n:
            blob.ref_count = n
            marked += 1
        if n <= 0:
            if blob.gc_eligible_at is None:
                blob.gc_eligible_at = now
                marked += 1
        elif blob.gc_eligible_at is not None:
            blob.gc_eligible_at = None
            marked += 1
    session.flush()
    return marked


def sweep_expired_blobs(
    session: Session,
    *,
    cool_off: timedelta = timedelta(hours=24),
    now: datetime | None = None,
    root: Path | None = None,
    dry_run: bool = False,
) -> GcResult:
    """Delete DB rows for blobs past cool-off; return paths for post-commit unlink.

    Does **not** unlink files. Callers must ``session.commit()`` then unlink
    ``result.paths_to_unlink`` (see ``run_gc_blobs``).
    """
    now = now or datetime.now(timezone.utc)
    root = root or blob_root()
    marked = mark_unreferenced_blobs(session, now=now)
    deleted = 0
    skipped = 0
    paths: list[Path] = []
    blobs = list(session.scalars(select(MessageBlob).where(MessageBlob.ref_count <= 0)).all())
    for blob in blobs:
        age_base = blob.gc_eligible_at or blob.created_at
        if age_base.tzinfo is None:
            age_base = age_base.replace(tzinfo=timezone.utc)
        if now - age_base < cool_off:
            skipped += 1
            continue
        path = root / blob.storage_path
        if not dry_run:
            paths.append(path)
            session.delete(blob)
        deleted += 1
    session.flush()
    return GcResult(
        marked=marked,
        deleted=deleted,
        skipped_cooloff=skipped,
        paths_to_unlink=tuple(paths),
    )


def unlink_gc_paths(paths: tuple[Path, ...] | list[Path]) -> int:
    """Phase 2: remove files after DB commit. Returns unlink count."""
    n = 0
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
                n += 1
        except OSError as exc:
            log.warning("gc unlink failed %s: %s", path, exc)
    return n


def run_gc_blobs(*, cool_off_hours: float = 24.0, dry_run: bool = False) -> dict:
    Session = __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()
    with Session() as session:
        result = sweep_expired_blobs(session, cool_off=timedelta(hours=cool_off_hours), dry_run=dry_run)
        paths = result.paths_to_unlink
        session.commit()
    unlinked = 0 if dry_run else unlink_gc_paths(paths)
    return {
        "status": "ok",
        "marked": result.marked,
        "deleted": result.deleted,
        "skipped": result.skipped_cooloff,
        "unlinked": unlinked,
        "dry_run": dry_run,
    }
