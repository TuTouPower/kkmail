"""Read models: unified inbox, folder stats, keyset message lists."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import Attachment, Folder, FolderStats, Message, MessageBody, MessageLocation


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


@dataclass(frozen=True, slots=True)
class AttachmentItem:
    id: uuid.UUID
    filename: str
    content_type: str | None
    size_bytes: int | None
    is_inline: bool


@dataclass(frozen=True, slots=True)
class MessageDetail:
    id: uuid.UUID
    account_id: uuid.UUID
    subject: str
    from_address: str
    from_name: str | None
    to_addresses: list[Any]
    cc_addresses: list[Any]
    sort_time: datetime
    is_read: bool
    has_attachments: bool
    snippet: str | None
    body_text: str | None
    body_html: str | None
    body_type: str  # html | text | empty
    parse_error: str | None
    attachments: list[AttachmentItem]


def get_message_detail(session: Session, message_id: uuid.UUID) -> MessageDetail | None:
    """Return message metadata + parsed body (if archived/parsed) + attachment list."""
    msg = session.get(Message, message_id)
    if msg is None:
        return None
    body = session.get(MessageBody, message_id)
    text_html = body.text_html if body else None
    text_plain = body.text_plain if body else None
    if text_html:
        body_type = "html"
    elif text_plain:
        body_type = "text"
    else:
        body_type = "empty"
    atts = list(
        session.scalars(select(Attachment).where(Attachment.message_id == message_id).order_by(Attachment.filename)).all()
    )
    return MessageDetail(
        id=msg.id,
        account_id=msg.account_id,
        subject=msg.subject,
        from_address=msg.from_address,
        from_name=msg.from_name,
        to_addresses=list(msg.to_addresses or []),
        cc_addresses=list(msg.cc_addresses or []),
        sort_time=msg.sort_time,
        is_read=msg.is_read,
        has_attachments=msg.has_attachments,
        snippet=msg.snippet,
        body_text=text_plain,
        body_html=text_html,
        body_type=body_type,
        parse_error=body.parse_error if body else None,
        attachments=[
            AttachmentItem(
                id=a.id,
                filename=a.filename,
                content_type=a.content_type,
                size_bytes=a.size_bytes,
                is_inline=a.is_inline,
            )
            for a in atts
        ],
    )
