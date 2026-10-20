"""Read models: unified inbox, folder stats, keyset message lists."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import Folder, FolderStats, Message, MessageLocation


@dataclass(frozen=True, slots=True)
class MessageListItem:
    id: uuid.UUID
    account_id: uuid.UUID
    subject: str
    from_address: str
    from_name: str | None
    sort_time: datetime
    is_read: bool
    has_attachments: bool
    snippet: str | None
    folder_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class MessagePage:
    items: list[MessageListItem]
    next_cursor: dict[str, Any] | None


def get_folder_stats(session: Session, folder_id: uuid.UUID) -> FolderStats | None:
    return session.get(FolderStats, folder_id)


def list_folder_stats_for_account(session: Session, account_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = session.execute(
        select(Folder, FolderStats)
        .outerjoin(FolderStats, FolderStats.folder_id == Folder.id)
        .where(Folder.account_id == account_id)
        .order_by(Folder.name.asc())
    ).all()
    out = []
    for folder, stats in rows:
        out.append(
            {
                "folder_id": str(folder.id),
                "remote_id": folder.remote_id,
                "name": folder.name,
                "role": folder.role,
                "total_count": stats.total_count if stats else 0,
                "unread_count": stats.unread_count if stats else 0,
            }
        )
    return out


def list_messages_keyset(
    session: Session,
    *,
    folder_ids: list[uuid.UUID],
    limit: int = 50,
    cursor_sort_time: datetime | None = None,
    cursor_message_id: uuid.UUID | None = None,
) -> MessagePage:
    if not folder_ids:
        return MessagePage(items=[], next_cursor=None)
    stmt = (
        select(Message, MessageLocation.folder_id)
        .join(MessageLocation, MessageLocation.message_id == Message.id)
        .where(MessageLocation.folder_id.in_(folder_ids))
    )
    if cursor_sort_time is not None and cursor_message_id is not None:
        stmt = stmt.where(
            or_(
                Message.sort_time < cursor_sort_time,
                and_(Message.sort_time == cursor_sort_time, Message.id < cursor_message_id),
            )
        )
    stmt = stmt.order_by(Message.sort_time.desc(), Message.id.desc()).limit(limit + 1)
    rows = list(session.execute(stmt).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        MessageListItem(
            id=m.id,
            account_id=m.account_id,
            subject=m.subject,
            from_address=m.from_address,
            from_name=m.from_name,
            sort_time=m.sort_time,
            is_read=m.is_read,
            has_attachments=m.has_attachments,
            snippet=m.snippet,
            folder_id=fid,
        )
        for m, fid in rows
    ]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = {"sort_time": last.sort_time.isoformat(), "message_id": str(last.id)}
    return MessagePage(items=items, next_cursor=next_cursor)


def unified_inbox(
    session: Session,
    *,
    account_ids: list[uuid.UUID] | None = None,
    limit: int = 50,
    cursor_sort_time: datetime | None = None,
    cursor_message_id: uuid.UUID | None = None,
) -> MessagePage:
    """Backend-aggregated inbox across accounts (role=inbox folders)."""
    stmt = select(Folder.id).where(Folder.role == "inbox")
    if account_ids:
        stmt = stmt.where(Folder.account_id.in_(account_ids))
    folder_ids = list(session.scalars(stmt).all())
    return list_messages_keyset(
        session,
        folder_ids=folder_ids,
        limit=limit,
        cursor_sort_time=cursor_sort_time,
        cursor_message_id=cursor_message_id,
    )
