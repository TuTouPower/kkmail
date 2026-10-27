"""Folder counters maintained from message_locations (one SQL aggregate, no ORM load)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import FolderStats, Message, MessageLocation


def recompute_folder_stats(session: Session, folder_id: uuid.UUID) -> FolderStats:
    stats = session.get(FolderStats, folder_id, with_for_update=True)
    if stats is None:
        # Race recovery (A167): a concurrent transaction may be creating
        # the row right now. Our INSERT can lose with IntegrityError while
        # a re-read still returns None (winner not yet committed, or the
        # row was cascade-deleted in between). Retry the insert/re-read
        # cycle a bounded number of times instead of falling through with
        # stats=None, and fail with a clear error if the row never
        # materialises.
        for _attempt in range(3):
            candidate = FolderStats(folder_id=folder_id)
            try:
                with session.begin_nested():
                    session.add(candidate)
                    session.flush()
                stats = candidate
                break
            except IntegrityError:
                stats = session.get(FolderStats, folder_id, with_for_update=True)
                if stats is not None:
                    break
        if stats is None:
            raise RuntimeError(
                f"folder_stats row for folder {folder_id} did not materialise after retries"
            )
    else:
        session.flush()
    total, unread, unknown = session.execute(
        select(
            func.count(),
            func.count().filter(Message.is_read.is_(False)),
            func.count().filter(Message.is_read.is_(None)),
        )
        .select_from(MessageLocation)
        .join(Message, Message.id == MessageLocation.message_id)
        .where(MessageLocation.folder_id == folder_id)
    ).one()
    stats.total_count = int(total or 0)
    stats.unread_count = None if unknown else int(unread or 0)
    stats.updated_at = datetime.now(timezone.utc)
    return stats
