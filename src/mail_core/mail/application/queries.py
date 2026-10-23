"""Read models: unified inbox, folder stats, keyset message lists."""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from pydantic import BaseModel
from sqlalchemy import and_, cast, func, or_, select, String
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
    body_preview: str = ""


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


def _list_item(m: Message, folder_id: Any, body_preview: str = "") -> MessageListItem:
    fid_uuid = uuid.UUID(str(folder_id)) if folder_id else None
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
        folder_id=fid_uuid,
        body_preview=body_preview,
    )


class _BodyPreviewParser(HTMLParser):
    """Extract visible body text for list display without changing stored mail data."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"head", "script", "style"}:
            self.hidden.append(tag)
        if not self.hidden:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self.hidden and self.hidden[-1] == tag:
            self.hidden.pop()
        if not self.hidden:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _body_previews(session: Session, messages: list[Message]) -> dict[uuid.UUID, str]:
    # One batch for the current page only; never load bodies when a provider snippet exists.
    ids = [m.id for m in messages if not m.snippet]
    if not ids:
        return {}
    rows = session.execute(
        select(MessageBody.message_id, MessageBody.text_plain, MessageBody.text_html)
        .where(MessageBody.message_id.in_(ids), MessageBody.parse_error.is_(None))
    ).all()
    previews = {}
    for mid, plain, html in rows:
        text = plain or ""
        if not text and html:
            parser = _BodyPreviewParser()
            parser.feed(html)
            parser.close()
            text = "".join(parser.parts)
        previews[mid] = " ".join(text.split())[:180]
    return previews


def messages_by_ids(session: Session, ids: list[uuid.UUID]) -> list[MessageListItem]:
    """Hydrate list rows for ``ids`` preserving the given order; batch-load body previews when needed."""
    if not ids:
        return []
    rows = session.execute(
        select(Message, MessageLocation.folder_id)
        .outerjoin(MessageLocation, MessageLocation.message_id == Message.id)
        .where(Message.id.in_(ids))
    ).all()
    previews = _body_previews(session, list({m.id: m for m, _ in rows}.values()))
    by_id: dict[uuid.UUID, MessageListItem] = {}
    for m, fid in rows:
        by_id.setdefault(m.id, _list_item(m, fid, previews.get(m.id, "")))
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
                "parent_remote_id": folder.parent_remote_id,
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
    is_read: bool | None = None,
    is_flagged: bool | None = None,
    sort_order: str = "desc",
) -> MessagePage:
    if sort_order not in ("asc", "desc"):
        raise ValueError(f"Invalid sort_order: {sort_order}, must be 'asc' or 'desc'")
    # Opaque cursor is atomic: decode raises InvalidCursor unless both halves exist.
    cursor_pair = decode_cursor(cursor) if cursor else None
    if not folder_ids:
        return MessagePage(items=[], next_cursor=None)
    stmt = (
        select(Message, func.min(cast(MessageLocation.folder_id, String)).label("folder_id"))
        .join(MessageLocation, MessageLocation.message_id == Message.id)
        .where(MessageLocation.folder_id.in_(folder_ids))
        .group_by(Message.id)
    )
    if is_read is not None:
        stmt = stmt.where(Message.is_read == is_read)
    if is_flagged is not None:
        stmt = stmt.where(Message.is_flagged == is_flagged)
    if cursor_pair is not None:
        cursor_sort_time, cursor_message_id = cursor_pair
        if sort_order == "asc":
            stmt = stmt.where(
                or_(
                    Message.sort_time > cursor_sort_time,
                    and_(Message.sort_time == cursor_sort_time, Message.id > cursor_message_id),
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    Message.sort_time < cursor_sort_time,
                    and_(Message.sort_time == cursor_sort_time, Message.id < cursor_message_id),
                )
            )
    if sort_order == "asc":
        stmt = stmt.order_by(Message.sort_time.asc(), Message.id.asc()).limit(limit + 1)
    else:
        stmt = stmt.order_by(Message.sort_time.desc(), Message.id.desc()).limit(limit + 1)
    rows = list(session.execute(stmt).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    previews = _body_previews(session, [m for m, _ in rows])
    items = [_list_item(m, fid, previews.get(m.id, "")) for m, fid in rows]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor(last.sort_time, last.id)
    return MessagePage(items=items, next_cursor=next_cursor)


def unified_inbox(
    session: Session,
    *,
    account_ids: list[uuid.UUID] | None = None,
    folder_id: uuid.UUID | None = None,
    limit: int = 50,
    cursor: str | None = None,
    is_read: bool | None = None,
    is_flagged: bool | None = None,
    folder_role: str = "inbox",
    sort_order: str = "desc",
) -> MessagePage:
    """Backend-aggregated inbox across accounts for a specified folder role or exact folder_id."""
    if folder_id is not None:
        folder = session.get(Folder, folder_id)
        if folder is None:
            raise LookupError(f"folder {folder_id} not found")
        if account_ids and folder.account_id not in account_ids:
            raise LookupError(f"folder {folder_id} does not belong to specified account")
        folder_ids = [folder.id]
    else:
        stmt = select(Folder.id).where(Folder.role == folder_role)
        if account_ids:
            stmt = stmt.where(Folder.account_id.in_(account_ids))
        folder_ids = list(session.scalars(stmt).all())
    return list_messages_keyset(
        session,
        folder_ids=folder_ids,
        limit=limit,
        cursor=cursor,
        is_read=is_read,
        is_flagged=is_flagged,
        sort_order=sort_order,
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


class AccountInboxStatsOut(BaseModel):
    account_id: uuid.UUID
    unread_count: int
    total_count: int


class GlobalStatsOut(BaseModel):
    total_unread: int
    accounts: list[AccountInboxStatsOut]


def query_global_inbox_stats(session: Session) -> GlobalStatsOut:
    """Return aggregated inbox stats across all accounts."""
    stmt = (
        select(
            Folder.account_id,
            func.coalesce(func.sum(FolderStats.unread_count), 0).label("unread_count"),
            func.coalesce(func.sum(FolderStats.total_count), 0).label("total_count"),
        )
        .select_from(FolderStats)
        .join(Folder, FolderStats.folder_id == Folder.id)
        .where(Folder.role == FolderRole.INBOX.value)
        .group_by(Folder.account_id)
        .order_by(Folder.account_id.asc())
    )
    rows = session.execute(stmt).all()
    accounts = [
        AccountInboxStatsOut(
            account_id=r[0],
            unread_count=int(r[1]),
            total_count=int(r[2]),
        )
        for r in rows
    ]
    total_unread = sum(a.unread_count for a in accounts)
    return GlobalStatsOut(total_unread=total_unread, accounts=accounts)

