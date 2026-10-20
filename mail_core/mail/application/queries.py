"""Read models: unified inbox, folder stats, keyset message lists."""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import FolderRole
from mail_core.mail.storage.models import Account, Attachment, Folder, FolderStats, Message, MessageBody, MessageLocation


@dataclass(frozen=True, slots=True)
class MessageListItem:
    id: uuid.UUID
    account_id: uuid.UUID
    subject: str
    from_address: str
    from_name: str | None
    sort_time: datetime
    is_read: bool
    is_flagged: bool
    has_attachments: bool
    snippet: str | None
    folder_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class MessagePage:
    items: list[MessageListItem]
    # Opaque keyset token; pass back verbatim as ``cursor``.
    next_cursor: str | None


class InvalidCursor(ValueError):
    """Cursor token is malformed."""


def encode_cursor(sort_time: datetime, message_id: uuid.UUID) -> str:
    raw = f"{sort_time.isoformat()}|{message_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(token: str) -> tuple[datetime, uuid.UUID]:
    """Decode opaque keyset token. Both halves are required — never partially apply."""
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad).decode()
        if "|" not in raw:
            raise InvalidCursor("invalid cursor")
        st, mid = raw.split("|", 1)
        if not st.strip() or not mid.strip():
            # Partial keyset (time without id or id without time) must not be ignored.
            raise InvalidCursor("invalid cursor")
        return datetime.fromisoformat(st), uuid.UUID(mid)
    except InvalidCursor:
        raise
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same client error
        raise InvalidCursor("invalid cursor") from exc


def _list_item(m: Message, folder_id: uuid.UUID | None) -> MessageListItem:
    return MessageListItem(
        id=m.id,
        account_id=m.account_id,
        subject=m.subject,
        from_address=m.from_address,
        from_name=m.from_name,
        sort_time=m.sort_time,
        is_read=m.is_read,
        is_flagged=m.is_flagged,
        has_attachments=m.has_attachments,
        snippet=m.snippet,
        folder_id=folder_id,
    )


def messages_by_ids(session: Session, ids: list[uuid.UUID]) -> list[MessageListItem]:
    """Hydrate list rows for ``ids`` preserving the given order (one query)."""
    if not ids:
        return []
    rows = session.execute(
        select(Message, MessageLocation.folder_id)
        .outerjoin(MessageLocation, MessageLocation.message_id == Message.id)
        .where(Message.id.in_(ids))
    ).all()
    by_id: dict[uuid.UUID, MessageListItem] = {}
    for m, fid in rows:
        by_id.setdefault(m.id, _list_item(m, fid))
    return [by_id[i] for i in ids if i in by_id]


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
    cursor: str | None = None,
) -> MessagePage:
    # Opaque cursor is atomic: decode raises InvalidCursor unless both halves exist.
    cursor_pair = decode_cursor(cursor) if cursor else None
    if not folder_ids:
        return MessagePage(items=[], next_cursor=None)
    stmt = (
        select(Message, MessageLocation.folder_id)
        .join(MessageLocation, MessageLocation.message_id == Message.id)
        .where(MessageLocation.folder_id.in_(folder_ids))
    )
    if cursor_pair is not None:
        cursor_sort_time, cursor_message_id = cursor_pair
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
    items = [_list_item(m, fid) for m, fid in rows]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(last.sort_time, last.id)
    return MessagePage(items=items, next_cursor=next_cursor)


def unified_inbox(
    session: Session,
    *,
    account_ids: list[uuid.UUID] | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> MessagePage:
    """Backend-aggregated inbox across accounts (role=inbox folders)."""
    stmt = select(Folder.id).where(Folder.role == FolderRole.INBOX.value)
    if account_ids:
        stmt = stmt.where(Folder.account_id.in_(account_ids))
    folder_ids = list(session.scalars(stmt).all())
    return list_messages_keyset(
        session,
        folder_ids=folder_ids,
        limit=limit,
        cursor=cursor,
    )


def select_display_body(text_html: str | None, text_plain: str | None) -> tuple[str, str]:
    """Prefer HTML, then plain text. Returns ``(body, body_type)`` where type is html|text|empty."""
    if text_html:
        return text_html, "html"
    if text_plain:
        return text_plain, "text"
    return "", "empty"


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
    is_flagged: bool
    has_attachments: bool
    snippet: str | None
    body_text: str | None
    body_html: str | None
    body: str
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
    display_body, body_type = select_display_body(text_html, text_plain)
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
        is_flagged=msg.is_flagged,
        has_attachments=msg.has_attachments,
        snippet=msg.snippet,
        body_text=text_plain,
        body_html=text_html,
        body=display_body,
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


def account_emails_by_id(session: Session, account_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not account_ids:
        return {}
    rows = session.execute(select(Account.id, Account.email).where(Account.id.in_(account_ids))).all()
    return {rid: email for rid, email in rows}
