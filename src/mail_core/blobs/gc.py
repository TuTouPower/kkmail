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
from mail_core.blobs.store import BlobStore
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
    skipped_invalid: int = 0  # rows whose digest/path failed canonical validation


def mark_unreferenced_blobs(session: Session, *, now: datetime | None = None) -> int:
    """Reconcile ref_count from links; stamp/clear ``gc_eligible_at``.

    Pages are committed one at a time (short transactions) and progress is
    logged per page; ``marked`` counts each changed blob once.
    """
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

        page_marked = 0
        for blob in blobs:
            n = int(link_counts.get(blob.id, 0)) + int(att_counts.get(blob.id, 0))
            prev = int(blob.ref_count)
            # A blob counts once in ``marked`` no matter how many of its
            # fields changed (ref_count correction + gc_eligible_at stamp
            # on the same row used to count twice).
            changed = False
            if prev != n:
                blob.ref_count = n
                changed = True
            if n <= 0:
                if blob.gc_eligible_at is None:
                    blob.gc_eligible_at = now
                    changed = True
            elif blob.gc_eligible_at is not None:
                blob.gc_eligible_at = None
                changed = True
            if changed:
                page_marked += 1

        marked += page_marked
        last_id = blobs[-1].id
        # Short per-page transactions: the reconcile scan must not hold one
        # transaction open across the whole message_blobs table.
        session.commit()
        log.info(
            "gc mark_unreferenced page done: last_id=%s page_marked=%d marked_total=%d",
            last_id,
            page_marked,
            marked,
        )
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

    Candidates are keyset-paged and each batch's deletions are committed
    before the next page is read. Does **not** unlink files: unlinking
    ``result.paths_to_unlink`` is still the caller's phase 2, after this
    function returns (see ``run_gc_blobs``).
    """
    now = now or datetime.now(timezone.utc)
    root = root or blob_root()
    # dry_run must not mutate ref_count / gc_eligible_at; only count candidates.
    marked = 0 if dry_run else mark_unreferenced_blobs(session, now=now)
    deleted = 0
    would_delete = 0
    skipped = 0
    skipped_invalid = 0
    paths: list[Path] = []
    # Paths are derived from the content digest via BlobStore.path_for —
    # the DB ``storage_path`` field is never joined onto the root directly,
    # so a polluted row cannot steer deletion outside the canonical layout.
    try:
        store: BlobStore | None = BlobStore(root)
    except Exception as exc:  # noqa: BLE001
        log.warning("gc sweep path validation unavailable: %s", exc)
        store = None
    last_id = None
    while True:
        query = (
            select(MessageBlob)
            .where(MessageBlob.ref_count <= 0)
            .order_by(MessageBlob.id)
            .limit(_GC_RECONCILE_BATCH_SIZE)
        )
        if last_id is not None:
            query = query.where(MessageBlob.id > last_id)
        blobs = list(session.scalars(query).all())
        if not blobs:
            break
        for blob in blobs:
            age_base = blob.gc_eligible_at or blob.created_at
            if age_base.tzinfo is None:
                age_base = age_base.replace(tzinfo=timezone.utc)
            if now - age_base < cool_off:
                skipped += 1
                continue
            if store is None:
                skipped_invalid += 1
                continue
            try:
                path = store.path_for(blob.content_sha256)
            except Exception as exc:  # noqa: BLE001
                log.warning("gc sweep skipped blob id=%s with non-canonical digest: %s", blob.id, exc)
                skipped_invalid += 1
                continue
            if dry_run:
                would_delete += 1
                continue
            paths.append(path)
            session.delete(blob)
            deleted += 1
        last_id = blobs[-1].id
        session.flush()
        if not dry_run:
            # Per-batch commit: the sweep must not load or hold the whole
            # expired set in a single transaction.
            session.commit()
    return GcResult(
        marked=marked,
        deleted=deleted,
        skipped_cooloff=skipped,
        paths_to_unlink=tuple(paths),
        would_delete=would_delete,
        skipped_invalid=skipped_invalid,
    )


def unlink_gc_paths(
    paths: tuple[Path, ...] | list[Path],
    *,
    session: Session | None = None,
    root: Path | None = None,
) -> int:
    """Phase 2: remove files after DB commit. Returns unlink count.

    Performs a second safety check against the DB before unlinking to prevent
    races where a concurrent archive re-referenced the same digest (V2-21 / R12).
    Coordinates via digest advisory lock to serialize with concurrent archive publishing.
    """
    root = Path(root or blob_root()).resolve()
    if not root.is_dir():
        return 0
    try:
        store = BlobStore(root)
    except Exception as exc:  # noqa: BLE001
        log.warning("gc unlink path validation unavailable: %s (skipping)", exc)
        return 0

    validated_paths: list[tuple[Path, str]] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_file() or path.is_symlink():
            continue
        digest = path.stem.lower()
        try:
            expected = store.path_for(digest)
            candidate = path.resolve()
        except Exception as exc:  # noqa: BLE001
            log.warning("gc unlink rejected non-canonical path %s: %s", path, exc)
            continue
        if candidate != expected:
            log.warning("gc unlink rejected path outside canonical blob layout: %s", path)
            continue
        validated_paths.append((path, digest))

    if not validated_paths:
        return 0

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
        for path, digest in validated_paths:
            try:
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
        "skipped_invalid": result.skipped_invalid,
        "unlinked": unlinked,
        "dry_run": dry_run,
    }
