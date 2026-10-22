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
        stats = FolderStats(folder_id=folder_id)
        try:
            with session.begin_nested():
                session.add(stats)
                session.flush()
        except IntegrityError:
            stats = session.get(FolderStats, folder_id, with_for_update=True)
            if stats is None:
                raise
    else:
        session.flush()
    total, unread = session.execute(
        select(
            func.count(),
            func.count().filter(Message.is_read.is_(False)),
        )
        .select_from(MessageLocation)
        .join(Message, Message.id == MessageLocation.message_id)
        .where(MessageLocation.folder_id == folder_id)
    ).one()
    stats.total_count = int(total or 0)
    stats.unread_count = int(unread or 0)
    stats.updated_at = datetime.now(timezone.utc)
    return stats
