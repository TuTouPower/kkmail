"""Read models: unified inbox, folder stats, keyset message lists."""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from pydantic import BaseModel
from sqlalchemy import and_, case, cast, func, or_, select, String
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import SyncStatus
from mail_core.mail.storage.models import Account, AccountGroup, Attachment, Folder, FolderStats, Message, MessageBody, MessageLocation

_BODY_PREVIEW_SOURCE_CHARS = 4096


@dataclass(frozen=True, slots=True)
class MessageFolderLocation:
    folder_id: uuid.UUID
    role: str


@dataclass(frozen=True, slots=True)
class MessageListItem:
    id: uuid.UUID
    account_id: uuid.UUID
    subject: str
    from_address: str
    from_name: str | None
    sort_time: datetime | None
    is_read: bool | None
    is_flagged: bool | None
    has_attachments: bool | None
    snippet: str | None
    folder_id: uuid.UUID | None
    locations: list[MessageFolderLocation]
    body_preview: str = ""


@dataclass(frozen=True, slots=True)
class MessagePage:
    items: list[MessageListItem]
    # Opaque keyset token; pass back verbatim as ``cursor``.
    next_cursor: str | None


class InvalidCursor(ValueError):
    """Cursor token is malformed."""


def encode_cursor(sort_time: datetime | None, message_id: uuid.UUID) -> str:
    timestamp = sort_time.isoformat() if sort_time is not None else ""
    raw = f"{timestamp}|{message_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(token: str) -> tuple[datetime | None, uuid.UUID]:
    """Decode a keyset token; an empty timestamp encodes an unknown time."""
    try:
        pad = "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(token + pad).decode()
        if "|" not in raw:
            raise InvalidCursor("invalid cursor")
        st, mid = raw.split("|", 1)
        if not mid.strip():
            raise InvalidCursor("invalid cursor")
        sort_time = datetime.fromisoformat(st) if st.strip() else None
        return sort_time, uuid.UUID(mid)
    except InvalidCursor:
        raise
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same client error
        raise InvalidCursor("invalid cursor") from exc


def _list_item(
    m: Message,
    folder_id: Any,
    body_preview: str = "",
    locations: list[MessageFolderLocation] | None = None,
) -> MessageListItem:
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
        locations=locations or [],
        body_preview=body_preview,
    )


def _folder_locations_by_message_ids(
    session: Session,
    message_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[MessageFolderLocation]]:
    locations: dict[uuid.UUID, list[MessageFolderLocation]] = {message_id: [] for message_id in message_ids}
    if not message_ids:
        return locations
    rows = session.execute(
        select(MessageLocation.message_id, Folder.id, Folder.role)
        .join(Message, Message.id == MessageLocation.message_id)
        .join(Folder, and_(Folder.id == MessageLocation.folder_id, Folder.account_id == Message.account_id))
        .where(MessageLocation.message_id.in_(message_ids))
        .order_by(MessageLocation.message_id, Folder.id)
    ).all()
    for message_id, folder_id, role in rows:
        locations[message_id].append(MessageFolderLocation(folder_id=folder_id, role=role))
    return locations


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
        select(
            MessageBody.message_id,
            func.substr(MessageBody.text_plain, 1, _BODY_PREVIEW_SOURCE_CHARS),
            func.substr(MessageBody.text_html, 1, _BODY_PREVIEW_SOURCE_CHARS),
        )
        .where(MessageBody.message_id.in_(ids))
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
    locations = _folder_locations_by_message_ids(session, list(dict.fromkeys(ids)))
    by_id: dict[uuid.UUID, MessageListItem] = {}
    for m, fid in rows:
        by_id.setdefault(m.id, _list_item(m, fid, previews.get(m.id, ""), locations.get(m.id, [])))
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
                "sync_status": folder.sync_status,
                "parent_remote_id": folder.parent_remote_id,
                "total_count": stats.total_count if stats else None,
                "unread_count": stats.unread_count if stats else None,
            }
        )
    return out


def list_messages_keyset(
    session: Session,
    *,
    folder_ids: list[uuid.UUID],
    preferred_folder_id: uuid.UUID | None = None,
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
    folder_id_text = cast(MessageLocation.folder_id, String)
    selected_folder_id = func.min(folder_id_text)
    if preferred_folder_id is not None:
        selected_folder_id = func.coalesce(
            func.min(
                case(
                    (MessageLocation.folder_id == preferred_folder_id, folder_id_text),
                    else_=None,
                )
            ),
            selected_folder_id,
        )
    stmt = (
        select(Message, selected_folder_id.label("folder_id"))
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
        if cursor_sort_time is None:
            id_after_cursor = (
                Message.id > cursor_message_id if sort_order == "asc" else Message.id < cursor_message_id
            )
            stmt = stmt.where(and_(Message.sort_time.is_(None), id_after_cursor))
        elif sort_order == "asc":
            stmt = stmt.where(
                or_(
                    Message.sort_time.is_(None),
                    Message.sort_time > cursor_sort_time,
                    and_(Message.sort_time == cursor_sort_time, Message.id > cursor_message_id),
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    Message.sort_time.is_(None),
                    Message.sort_time < cursor_sort_time,
                    and_(Message.sort_time == cursor_sort_time, Message.id < cursor_message_id),
                )
            )
    if sort_order == "asc":
        stmt = stmt.order_by(Message.sort_time.asc().nulls_last(), Message.id.asc()).limit(limit + 1)
    else:
        stmt = stmt.order_by(Message.sort_time.desc().nulls_last(), Message.id.desc()).limit(limit + 1)
    rows = list(session.execute(stmt).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    previews = _body_previews(session, [m for m, _ in rows])
    locations = _folder_locations_by_message_ids(session, [message.id for message, _ in rows])
    items = [
        _list_item(m, fid, previews.get(m.id, ""), locations.get(m.id, []))
        for m, fid in rows
    ]
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
        if account_ids is not None and folder.account_id not in account_ids:
            raise LookupError(f"folder {folder_id} does not belong to specified account")
        folder_ids = [folder.id]
    else:
        stmt = select(Folder.id).where(Folder.role == folder_role)
        if account_ids is not None:
            stmt = stmt.where(Folder.account_id.in_(account_ids))
        folder_ids = list(session.scalars(stmt).all())
    return list_messages_keyset(
        session,
        folder_ids=folder_ids,
        preferred_folder_id=folder_id,
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
    sort_time: datetime | None
    is_read: bool | None
    is_flagged: bool | None
    has_attachments: bool | None
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
    unread_count: int | None
    total_count: int | None


class GlobalStatsOut(BaseModel):
    total_unread: int | None
    accounts: list[AccountInboxStatsOut]


def _query_inbox_stats(
    session: Session,
    *,
    folder_role: str,
    group_id: uuid.UUID | None,
) -> GlobalStatsOut:
    stmt = (
        select(
            Account.id.label("account_id"),
            func.count(Folder.id).label("folder_count"),
            func.count(FolderStats.folder_id).label("stats_count"),
            func.sum(FolderStats.unread_count).label("unread_count"),
            func.sum(FolderStats.total_count).label("total_count"),
            func.count(FolderStats.unread_count).label("known_unread_count"),
            Account.sync_enabled.label("sync_enabled"),
            Account.sync_status.label("sync_status"),
        )
        .select_from(Account)
        .outerjoin(Folder, (Folder.account_id == Account.id) & (Folder.role == folder_role))
        .outerjoin(FolderStats, FolderStats.folder_id == Folder.id)
        .group_by(Account.id, Account.sync_enabled, Account.sync_status)
        .where(Account.sync_enabled.is_(True))
        .order_by(Account.id.asc())
    )
    if group_id is not None:
        stmt = stmt.where(Account.group_id == group_id)

    accounts: list[AccountInboxStatsOut] = []
    active_accounts: list[AccountInboxStatsOut] = []
    for row in session.execute(stmt).all():
        values = row._mapping
        if not values["sync_enabled"]:
            continue
        folder_count = values["folder_count"]
        stats_count = values["stats_count"]
        known_unread_count = values["known_unread_count"]
        unread = int(values["unread_count"]) if folder_count > 0 and folder_count == known_unread_count else None
        total = int(values["total_count"]) if folder_count > 0 and folder_count == stats_count else None
        acc_out = AccountInboxStatsOut(
            account_id=values["account_id"], unread_count=unread, total_count=total
        )
        accounts.append(acc_out)
        sync_enabled = bool(values["sync_enabled"])
        sync_status = str(values["sync_status"] or SyncStatus.IDLE.value)
        is_faulty_without_target = folder_count == 0 and (
            not sync_enabled or sync_status in (SyncStatus.FAILED.value, SyncStatus.AUTH_FAILED.value)
        )
        if not is_faulty_without_target:
            active_accounts.append(acc_out)

    total_unread = None if any(account.unread_count is None for account in active_accounts) else sum(
        account.unread_count or 0 for account in active_accounts
    )
    return GlobalStatsOut(total_unread=total_unread, accounts=accounts)


def query_global_inbox_stats(session: Session, *, folder_role: str = "inbox") -> GlobalStatsOut:
    """Return stats for a folder role, keeping missing folder stats unknown."""
    return _query_inbox_stats(session, folder_role=folder_role, group_id=None)


def query_group_inbox_stats(session: Session, group_id: uuid.UUID, *, folder_role: str = "inbox") -> GlobalStatsOut:
    """Return role counts for every current member, including unknown counts."""
    if session.get(AccountGroup, group_id) is None:
        raise LookupError("group not found")
    return _query_inbox_stats(session, folder_role=folder_role, group_id=group_id)
