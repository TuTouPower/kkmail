"""Folder counters maintained from message_locations (one SQL aggregate, no ORM load)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import FolderStats, Message, MessageLocation


def recompute_folder_stats(session: Session, folder_id: uuid.UUID) -> FolderStats:
    total, unread = session.execute(
        select(
            func.count(),
            func.count().filter(Message.is_read.is_(False)),
        )
        .select_from(MessageLocation)
        .join(Message, Message.id == MessageLocation.message_id)
        .where(MessageLocation.folder_id == folder_id)
    ).one()
    stats = session.get(FolderStats, folder_id)
    if stats is None:
        stats = FolderStats(folder_id=folder_id)
        session.add(stats)
    stats.total_count = int(total or 0)
    stats.unread_count = int(unread or 0)
    stats.updated_at = datetime.now(timezone.utc)
    return stats
