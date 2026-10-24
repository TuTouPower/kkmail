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
from mail_core.blobs.quota import acquire_blob_digest_lock, digest_to_lock_id
from mail_core.mail.storage.models import Attachment, MessageBlob, MessageBlobLink

log = logging.getLogger("mail_core.blobs.gc")
_GC_RECONCILE_BATCH_SIZE = 1000


@dataclass(frozen=True, slots=True)
class GcResult:
    marked: int
    deleted: int
    skipped_cooloff: int
    paths_to_unlink: tuple[Path, ...] = ()
    would_delete: int = 0  # dry_run candidates; never counted in ``deleted``


def mark_unreferenced_blobs(session: Session, *, now: datetime | None = None) -> int:
    """Reconcile ref_count from links; stamp/clear ``gc_eligible_at``."""
    now = now or datetime.now(timezone.utc)
    marked = 0
    last_id = None
    while True:
        query = select(MessageBlob).order_by(MessageBlob.id).limit(_GC_RECONCILE_BATCH_SIZE)
        if last_id is not None:
            query = query.where(MessageBlob.id > last_id)
        blobs = list(session.scalars(query).all())
        if not blobs:
            break

        blob_ids = [blob.id for blob in blobs]
        link_counts = dict(
            session.execute(
                select(MessageBlobLink.blob_id, func.count())
                .where(MessageBlobLink.blob_id.in_(blob_ids))
                .group_by(MessageBlobLink.blob_id)
            ).all()
        )
        att_counts = dict(
            session.execute(
                select(Attachment.blob_id, func.count())
                .where(Attachment.blob_id.in_(blob_ids))
                .where(Attachment.blob_id.is_not(None))
                .group_by(Attachment.blob_id)
            ).all()
        )

        for blob in blobs:
            n = int(link_counts.get(blob.id, 0)) + int(att_counts.get(blob.id, 0))
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

        last_id = blobs[-1].id
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
    # dry_run must not mutate ref_count / gc_eligible_at; only count candidates.
    marked = 0 if dry_run else mark_unreferenced_blobs(session, now=now)
    deleted = 0
    would_delete = 0
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
        if dry_run:
            would_delete += 1
            continue
        paths.append(path)
        session.delete(blob)
        deleted += 1
    session.flush()
    return GcResult(
        marked=marked,
        deleted=deleted,
        skipped_cooloff=skipped,
        paths_to_unlink=tuple(paths),
        would_delete=would_delete,
    )


def unlink_gc_paths(
    paths: tuple[Path, ...] | list[Path],
    *,
    session: Session | None = None,
) -> int:
    """Phase 2: remove files after DB commit. Returns unlink count.

    Performs a second safety check against the DB before unlinking to prevent
    races where a concurrent archive re-referenced the same digest (V2-21 / R12).
    Coordinates via digest advisory lock to serialize with concurrent archive publishing.
    """
    n = 0
    own_session = None
    if session is None:
        try:
            Session = __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()
            own_session = Session()
            check_session = own_session
        except Exception:
            check_session = None
    else:
        check_session = session

    try:
        for path in paths:
            try:
                if not path.is_file():
                    continue
                digest = path.stem.lower()
                if len(digest) == 64:
                    if check_session is None:
                        log.warning("gc unlink safety check has no db session for %s; skipping", path)
                        continue
                    try:
                        if own_session is not None:
                            with own_session.begin():
                                acquire_blob_digest_lock(own_session, digest)
                                live_refs = own_session.scalar(
                                    select(func.count())
                                    .select_from(MessageBlob)
                                    .where(MessageBlob.content_sha256 == digest)
                                ) or 0
                                if int(live_refs) > 0:
                                    log.info("gc unlink skipped newly referenced blob: %s", path)
                                    continue
                                path.unlink(missing_ok=True)
                                n += 1
                        else:
                            acquire_blob_digest_lock(check_session, digest)
                            live_refs = check_session.scalar(
                                select(func.count())
                                .select_from(MessageBlob)
                                .where(MessageBlob.content_sha256 == digest)
                            ) or 0
                            if int(live_refs) > 0:
                                log.info("gc unlink skipped newly referenced blob: %s", path)
                                continue
                            path.unlink(missing_ok=True)
                            n += 1
                    except Exception as exc:
                        log.warning("gc unlink safety check query error for %s: %s (skipping)", path, exc)
                        continue
                else:
                    path.unlink(missing_ok=True)
                    n += 1
            except OSError as exc:
                log.warning("gc unlink failed %s: %s", path, exc)
    finally:
        if own_session is not None:
            own_session.close()

    return n


def run_gc_blobs(*, cool_off_hours: float = 24.0, dry_run: bool = False) -> dict:
    Session = __import__("mail_core.db.session", fromlist=["get_session_factory"]).get_session_factory()
    with Session() as session:
        result = sweep_expired_blobs(session, cool_off=timedelta(hours=cool_off_hours), dry_run=dry_run)
        paths = result.paths_to_unlink
        if dry_run:
            session.rollback()  # never persist side effects from a dry run
        else:
            session.commit()
    unlinked = 0 if dry_run else unlink_gc_paths(paths)
    return {
        "status": "ok",
        "marked": result.marked,
        "deleted": result.deleted,
        "would_delete": result.would_delete,
        "skipped": result.skipped_cooloff,
        "unlinked": unlinked,
        "dry_run": dry_run,
    }
