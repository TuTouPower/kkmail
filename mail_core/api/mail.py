"""Mail read/mutation API: unified inbox, folder stats, search, detail, flags, trash, attachments.

Routes call the application layer only (queries / search / mutations / attachments).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mail_core.api.http_headers import content_disposition_attachment
from mail_core.db.session import get_session_factory
from mail_core.mail.application.attachments import (
    AttachmentAccessError,
    PathTraversalRejected,
    load_attachment,
)
from mail_core.mail.application.mutations import MutationResult, set_message_flagged, set_message_read, trash_message
from mail_core.mail.application.queries import (
    InvalidCursor,
    MessageListItem,
    account_emails_by_id,
    get_folder_stats,
    get_message_detail,
    list_folder_stats_for_account,
    unified_inbox,
)
from mail_core.mail.application.search import search_messages_page

router = APIRouter(prefix="/api/mail", tags=["mail"])


class MessageOut(BaseModel):
    id: str
    account_id: str
    account_email: str | None = None
    subject: str
    from_address: str
    from_name: str | None
    sort_time: datetime
    is_read: bool
    is_flagged: bool
    has_attachments: bool
    snippet: str | None
    folder_id: str | None


class PageOut(BaseModel):
    items: list[MessageOut]
    next_cursor: str | None = Field(None, description="Opaque keyset token; pass back as `cursor`.")


class SearchPageOut(BaseModel):
    query: str
    items: list[MessageOut]
    total: int
    offset: int
    next_offset: int | None


class FolderStatsOut(BaseModel):
    folder_id: str
    total_count: int
    unread_count: int
    updated_at: datetime | None = None


class AccountFolderStatsOut(BaseModel):
    account_id: str
    folders: list[dict]


class AttachmentOut(BaseModel):
    id: str
    name: str
    contentType: str | None
    size: int | None
    is_inline: bool


class MessageDetailOut(BaseModel):
    id: str
    account_id: str
    subject: str
    from_address: str
    from_name: str | None
    # Display helpers for the reader.
    from_: str = Field(serialization_alias="from")
    to: str
    cc: str
    date: datetime
    is_read: bool
    is_flagged: bool
    has_attachments: bool
    snippet: str | None
    body: str
    body_type: str
    parse_error: str | None
    attachments: list[AttachmentOut]


class ReadBody(BaseModel):
    is_read: bool


class FlagBody(BaseModel):
    is_flagged: bool


class MutationOut(BaseModel):
    id: str
    account_id: str
    operation_id: str
    is_read: bool | None = None
    is_flagged: bool | None = None
    success: bool = True


def _rows(items: list[MessageListItem], emails: dict) -> list[MessageOut]:
    return [
        MessageOut(
            id=str(i.id),
            account_id=str(i.account_id),
            account_email=emails.get(i.account_id),
            subject=i.subject,
            from_address=i.from_address,
            from_name=i.from_name,
            sort_time=i.sort_time,
            is_read=i.is_read,
            is_flagged=i.is_flagged,
            has_attachments=i.has_attachments,
            snippet=i.snippet,
            folder_id=str(i.folder_id) if i.folder_id else None,
        )
        for i in items
    ]


def _mutation_out(r: MutationResult) -> MutationOut:
    return MutationOut(
        id=str(r.message_id),
        account_id=str(r.account_id),
        operation_id=str(r.operation_id),
        is_read=r.is_read,
        is_flagged=r.is_flagged,
    )


@router.get("/inbox", response_model=PageOut)
def api_unified_inbox(
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, description="`next_cursor` from the previous page"),
    account_id: UUID | None = None,
) -> PageOut:
    Session = get_session_factory()
    with Session() as session:
        try:
            page = unified_inbox(session, account_ids=[account_id] if account_id else None, limit=limit, cursor=cursor)
        except InvalidCursor as exc:
            raise HTTPException(400, str(exc)) from exc
        emails = account_emails_by_id(session, [i.account_id for i in page.items])
        return PageOut(items=_rows(page.items, emails), next_cursor=page.next_cursor)


@router.get("/accounts/{account_id}/folder-stats", response_model=AccountFolderStatsOut)
def api_folder_stats(account_id: UUID) -> AccountFolderStatsOut:
    Session = get_session_factory()
    with Session() as session:
        return AccountFolderStatsOut(account_id=str(account_id), folders=list_folder_stats_for_account(session, account_id))


@router.get("/folders/{folder_id}/stats", response_model=FolderStatsOut)
def api_one_folder_stats(folder_id: UUID) -> FolderStatsOut:
    Session = get_session_factory()
    with Session() as session:
        stats = get_folder_stats(session, folder_id)
        if stats is None:
            raise HTTPException(404, "folder stats not found")
        return FolderStatsOut(
            folder_id=str(folder_id),
            total_count=stats.total_count,
            unread_count=stats.unread_count,
            updated_at=stats.updated_at,
        )


@router.get("/search", response_model=SearchPageOut)
def api_search(
    q: str = Query(..., min_length=1, max_length=256),
    account_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10_000),
) -> SearchPageOut:
    """Ranked search; rows are hydrated like /inbox. Paginate with `next_offset`."""
    Session = get_session_factory()
    with Session() as session:
        page = search_messages_page(
            session,
            query=q,
            account_ids=[account_id] if account_id else None,
            limit=limit,
            offset=offset,
        )
        emails = account_emails_by_id(session, [i.account_id for i in page.items])
        return SearchPageOut(
            query=page.query,
            items=_rows(page.items, emails),
            total=page.total,
            offset=page.offset,
            next_offset=page.next_offset,
        )


@router.get("/messages/{message_id}", response_model=MessageDetailOut, response_model_by_alias=True)
def api_get_message(message_id: UUID) -> MessageDetailOut:
    """Message metadata + parsed body + attachments (by UUID)."""
    Session = get_session_factory()
    with Session() as session:
        d = get_message_detail(session, message_id)
        if d is None:
            raise HTTPException(404, "message not found")
        return MessageDetailOut(
            id=str(d.id),
            account_id=str(d.account_id),
            subject=d.subject,
            from_address=d.from_address,
            from_name=d.from_name,
            from_=(f"{d.from_name} <{d.from_address}>" if d.from_name else d.from_address),
            to=", ".join(str(x) for x in d.to_addresses) if d.to_addresses else "",
            cc=", ".join(str(x) for x in d.cc_addresses) if d.cc_addresses else "",
            date=d.sort_time,
            is_read=d.is_read,
            is_flagged=d.is_flagged,
            has_attachments=d.has_attachments,
            snippet=d.snippet,
            body=(d.body_html if d.body_type == "html" else (d.body_text or "")) or "",
            body_type=d.body_type,
            parse_error=d.parse_error,
            attachments=[
                AttachmentOut(
                    id=str(a.id),
                    name=a.filename,
                    contentType=a.content_type,
                    size=a.size_bytes,
                    is_inline=a.is_inline,
                )
                for a in d.attachments
            ],
        )


@router.post("/messages/{message_id}/read", response_model=MutationOut)
def api_set_message_read(message_id: UUID, body: ReadBody) -> MutationOut:
    """Local-first mark read/unread + enqueue remote mark_read. Body is required."""
    Session = get_session_factory()
    with Session() as session:
        try:
            result = set_message_read(session, message_id, is_read=body.is_read)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        session.commit()
        return _mutation_out(result)


@router.post("/messages/{message_id}/flag", response_model=MutationOut)
def api_set_message_flag(message_id: UUID, body: FlagBody) -> MutationOut:
    """Local-first flag/unflag + enqueue remote set_flag. Body is required."""
    Session = get_session_factory()
    with Session() as session:
        try:
            result = set_message_flagged(session, message_id, is_flagged=body.is_flagged)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        session.commit()
        return _mutation_out(result)


@router.post("/messages/{message_id}/trash", response_model=MutationOut)
def api_trash_message(message_id: UUID) -> MutationOut:
    """Local-first trash + enqueue remote trash."""
    Session = get_session_factory()
    with Session() as session:
        try:
            result = trash_message(session, message_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        session.commit()
        return _mutation_out(result)


@router.get(
    "/attachments/{attachment_id}",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
def api_get_attachment(attachment_id: str):
    """Download attachment by UUID only — path parameters are rejected (M5)."""
    Session = get_session_factory()
    with Session() as session:
        try:
            payload = load_attachment(session, attachment_id)
        except PathTraversalRejected as exc:
            raise HTTPException(400, str(exc)) from exc
        except AttachmentAccessError as exc:
            raise HTTPException(404, str(exc)) from exc
    headers = {
        "Content-Disposition": content_disposition_attachment(payload.filename),
        "X-Content-SHA256": payload.content_sha256,
        "X-Content-Type-Options": "nosniff",
    }
    if payload.size_bytes is not None:
        headers["X-Attachment-Size"] = str(payload.size_bytes)
    media = payload.content_type or "application/octet-stream"
    # Stream-decrypt chunk by chunk; never materialise the whole attachment.
    return StreamingResponse(payload.open_stream(), media_type=media, headers=headers)


@router.get("/attachments/by-path/{path:path}", include_in_schema=False)
def api_get_attachment_by_path_rejected(path: str):
    """Explicitly reject path-shaped attachment access (architecture M5)."""
    raise HTTPException(400, "attachment access by filesystem path is forbidden; use attachment UUID")
