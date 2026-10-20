"""Delayed blob GC (architecture §10.2)."""

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


def mark_unreferenced_blobs(session: Session) -> int:
    blobs = list(session.scalars(select(MessageBlob)).all())
    marked = 0
    for blob in blobs:
        n = session.scalar(
            select(func.count()).select_from(MessageBlobLink).where(MessageBlobLink.blob_id == blob.id)
        ) or 0
        if int(blob.ref_count) != int(n):
            blob.ref_count = int(n)
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
    """Delete blobs with ref_count==0 whose created_at is older than cool_off.

    TODO: stamp an explicit ``gc_eligible_at`` when ref_count hits 0 for tighter semantics.
    """
    now = now or datetime.now(timezone.utc)
    root = root or blob_root()
    marked = mark_unreferenced_blobs(session)
    deleted = 0
    skipped = 0
    blobs = list(session.scalars(select(MessageBlob).where(MessageBlob.ref_count <= 0)).all())
    for blob in blobs:
        age_base = blob.created_at
        if age_base.tzinfo is None:
            age_base = age_base.replace(tzinfo=timezone.utc)
        if now - age_base < cool_off:
            skipped += 1
            continue
        path = root / blob.storage_path
        if not dry_run:
            try:
                if path.is_file():
                    path.unlink()
            except OSError as exc:
                log.warning("gc unlink failed %s: %s", path, exc)
                continue
            session.delete(blob)
        deleted += 1
    session.flush()
    return GcResult(marked=marked, deleted=deleted, skipped_cooloff=skipped)


def run_gc_blobs(*, cool_off_hours: float = 24.0, dry_run: bool = False) -> dict:
    Session = __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()
    with Session() as session:
        result = sweep_expired_blobs(session, cool_off=timedelta(hours=cool_off_hours), dry_run=dry_run)
        session.commit()
        return {
            "status": "ok",
            "marked": result.marked,
            "deleted": result.deleted,
            "skipped": result.skipped_cooloff,
            "dry_run": dry_run,
        }
