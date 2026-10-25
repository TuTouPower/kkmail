"""Mail read/mutation API: unified inbox, folder stats, search, detail, flags, trash, attachments.

Routes call the application layer only (queries / search / mutations / attachments).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mail_core.api.http_headers import content_disposition_attachment
from mail_core.db.session import get_session_factory
from mail_core.accounts import account_ids_for_group
from mail_core.mail.application.attachments import (
    AttachmentAccessError,
    PathTraversalRejected,
    load_attachment,
)
from mail_core.mail.application.mutations import (
    MARK_ALL_READ_BATCH_SIZE,
    MutationResult,
    UnaddressableMessageError,
    mark_all_messages_read,
    set_message_flagged,
    set_message_read,
    trash_message,
)
from mail_core.mail.application.queries import (
    GlobalStatsOut,
    InvalidCursor,
    MessageDetail,
    MessageListItem,
    account_emails_by_id,
    get_folder_stats,
    list_folder_stats_for_account,
    query_global_inbox_stats,
    query_group_inbox_stats,
    unified_inbox,
)
from mail_core.mail.application.message_details import (
    MessageArchiveStateUnavailable,
    MessageBodyAlreadyArchived,
    MessageHasNoProviderRemoteId,
    get_message_detail_with_archive_status,
    sync_message_body,
)
from mail_core.mail.application.search import search_messages_page
from mail_core.mail.storage.models import MessageArchiveState

router = APIRouter(prefix="/api/mail", tags=["mail"])
_MEDIA_TYPE_TOKEN = r"[A-Za-z0-9!#$%&'*+.^_`|~-]+"
_MEDIA_TYPE_PATTERN = re.compile(rf"{_MEDIA_TYPE_TOKEN}/{_MEDIA_TYPE_TOKEN}", re.ASCII)


def _safe_attachment_media_type(value: str | None) -> str:
    if value and _MEDIA_TYPE_PATTERN.fullmatch(value):
        return value
    return "application/octet-stream"


class MessageOut(BaseModel):
    id: str
    account_id: str
    account_email: str | None = None
    subject: str
    from_address: str
    from_name: str | None
    sort_time: datetime | None
    is_read: bool | None
    is_flagged: bool | None
    has_attachments: bool | None
    snippet: str | None
    body_preview: str = Field("", description="Display-only fallback from an existing body when snippet is empty; never persisted.")
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
    unread_count: int | None
    updated_at: datetime | None = None


class AccountFolderStatsItemOut(BaseModel):
    folder_id: UUID
    role: str
    name: str
    sync_status: str
    total_count: int | None
    unread_count: int | None
    remote_id: str
    parent_remote_id: str | None = None


class AccountFolderStatsOut(BaseModel):
    account_id: str
    folders: list[AccountFolderStatsItemOut]


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
    date: datetime | None
    is_read: bool | None
    is_flagged: bool | None
    has_attachments: bool | None
    snippet: str | None
    body: str
    body_type: str
    parse_error: str | None
    is_archived: bool | None
    archive_state: str | None = None
    archive_has_error: bool = False
    attachments: list[AttachmentOut]


def _detail_out(
    detail: MessageDetail,
    is_archived: bool | None,
    archive_state: str | None = None,
    archive_has_error: bool = False,
) -> MessageDetailOut:
    return MessageDetailOut(
        id=str(detail.id),
        account_id=str(detail.account_id),
        subject=detail.subject,
        from_address=detail.from_address,
        from_name=detail.from_name,
        from_=(f"{detail.from_name} <{detail.from_address}>" if detail.from_name else detail.from_address),
        to=", ".join(str(value) for value in detail.to_addresses) if detail.to_addresses else "",
        cc=", ".join(str(value) for value in detail.cc_addresses) if detail.cc_addresses else "",
        date=detail.sort_time,
        is_read=detail.is_read,
        is_flagged=detail.is_flagged,
        has_attachments=detail.has_attachments,
        snippet=detail.snippet,
        body=detail.body,
        body_type=detail.body_type,
        parse_error=detail.parse_error,
        is_archived=is_archived,
        archive_state=archive_state,
        archive_has_error=archive_has_error,
        attachments=[
            AttachmentOut(
                id=str(attachment.id),
                name=attachment.filename,
                contentType=attachment.content_type,
                size=attachment.size_bytes,
                is_inline=attachment.is_inline,
            )
            for attachment in detail.attachments
        ],
    )


class ReadBody(BaseModel):
    is_read: bool


class FlagBody(BaseModel):
    is_flagged: bool


class MarkAllReadBody(BaseModel):
    account_id: UUID | None = None
    group_id: UUID | None = None
    folder_role: str | None = "inbox"
    folder_id: UUID | None = None
    is_flagged: bool | None = None


class MarkAllReadOut(BaseModel):
    success: bool = True
    count: int
    account_id: str | None = None
    scope_type: Literal["global", "account", "group", "folder"]
    scope_id: str | None


class MutationOut(BaseModel):
    id: str
    account_id: str
    operation_id: str | None = None
    is_read: bool | None = None
    is_flagged: bool | None = None
    success: bool = True


class SyncBodyAcceptedOut(BaseModel):
    message_id: str
    job_id: str
    status: Literal["queued"]


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
            body_preview=i.body_preview,
            folder_id=str(i.folder_id) if i.folder_id else None,
        )
        for i in items
    ]


def _mutation_out(r: MutationResult) -> MutationOut:
    return MutationOut(
        id=str(r.message_id),
        account_id=str(r.account_id),
        operation_id=str(r.operation_id) if r.operation_id is not None else None,
        is_read=r.is_read,
        is_flagged=r.is_flagged,
    )


@router.get("/stats", response_model=GlobalStatsOut)
def api_global_inbox_stats(group_id: UUID | None = None, folder_role: str = "inbox") -> GlobalStatsOut:
    Session = get_session_factory()
    with Session() as session:
        if group_id is not None:
            try:
                return query_group_inbox_stats(session, group_id, folder_role=folder_role)
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc
        return query_global_inbox_stats(session, folder_role=folder_role)


@router.get("/inbox", response_model=PageOut)
def api_unified_inbox(
    limit: int = Query(50, ge=1, le=200),
    cursor: str | None = Query(None, description="`next_cursor` from the previous page"),
    account_id: UUID | None = None,
    group_id: UUID | None = None,
    is_read: bool | None = Query(None, description="Filter messages by read status"),
    is_flagged: bool | None = Query(None, description="Filter messages by flagged status"),
    folder_role: str = Query("inbox", description="Folder role to query (default: inbox)"),
    folder_id: UUID | None = Query(None, description="Specific folder ID to query"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$", description="Sort order by sort_time (desc or asc)"),
) -> PageOut:
    Session = get_session_factory()
    with Session() as session:
        if group_id is not None and (account_id is not None or folder_id is not None):
            raise HTTPException(400, "group_id cannot be combined with account_id or folder_id")
        try:
            account_ids = account_ids_for_group(session, group_id) if group_id is not None else ([account_id] if account_id else None)
            page = unified_inbox(
                session,
                account_ids=account_ids,
                folder_id=folder_id,
                limit=limit,
                cursor=cursor,
                is_read=is_read,
                is_flagged=is_flagged,
                folder_role=folder_role,
                sort_order=sort_order,
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
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
    group_id: UUID | None = None,
    folder_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10_000),
) -> SearchPageOut:
    """Ranked search; rows are hydrated like /inbox. Paginate with `next_offset`."""
    q = q.strip()
    if not q:
        raise HTTPException(422, "search query must not be blank")
    Session = get_session_factory()
    with Session() as session:
        if group_id is not None and (account_id is not None or folder_id is not None):
            raise HTTPException(400, "group_id cannot be combined with account_id or folder_id")
        try:
            account_ids = account_ids_for_group(session, group_id) if group_id is not None else ([account_id] if account_id else None)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        page = search_messages_page(
            session,
            query=q,
            account_ids=account_ids,
            folder_id=folder_id,
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
        result = get_message_detail_with_archive_status(session, message_id)
        if result is None:
            raise HTTPException(404, "message not found")
        state = session.get(MessageArchiveState, message_id)
        return _detail_out(
            *result,
            archive_state=state.state if state is not None else None,
            archive_has_error=bool(state and state.last_error),
        )


@router.post(
    "/messages/{message_id}/sync-body",
    response_model=SyncBodyAcceptedOut,
    response_model_by_alias=True,
    status_code=202,
)
def api_sync_message_body(message_id: UUID) -> SyncBodyAcceptedOut:
    """Queue an on-demand highest-priority body sync for a message."""
    try:
        job_id = sync_message_body(message_id)
    except MessageHasNoProviderRemoteId as exc:
        raise HTTPException(409, str(exc)) from exc
    except (MessageArchiveStateUnavailable, MessageBodyAlreadyArchived) as exc:
        raise HTTPException(409, str(exc)) from exc
    if job_id is None:
        raise HTTPException(404, "message not found")
    return SyncBodyAcceptedOut(message_id=str(message_id), job_id=str(job_id), status="queued")


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


@router.post("/mark-all-read", response_model=MarkAllReadOut)
def api_mark_all_read(body: MarkAllReadBody) -> MarkAllReadOut:
    """Batch mark messages read across the matching scope (folder/account/flag)."""
    Session = get_session_factory()
    if body.group_id is not None and (body.account_id is not None or body.folder_id is not None):
        raise HTTPException(400, "group_id cannot be combined with account_id or folder_id")
    group_account_ids = None
    if body.group_id is not None:
        with Session() as scope_session:
            try:
                group_account_ids = account_ids_for_group(scope_session, body.group_id)
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc
    if body.group_id is not None:
        scope_type, scope_id = "group", str(body.group_id)
    elif body.folder_id is not None:
        scope_type, scope_id = "folder", str(body.folder_id)
    elif body.account_id is not None:
        scope_type, scope_id = "account", str(body.account_id)
    else:
        scope_type, scope_id = "global", None

    total_count = 0
    after_message_id = None
    while True:
        with Session() as session:
            try:
                batch = mark_all_messages_read(
                    session,
                    account_id=body.account_id,
                    folder_role=body.folder_role,
                    folder_id=body.folder_id,
                    is_flagged=body.is_flagged,
                    group_id=body.group_id if group_account_ids is None else None,
                    account_ids=group_account_ids,
                    after_message_id=after_message_id,
                    limit=MARK_ALL_READ_BATCH_SIZE,
                )
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc
            session.commit()
        total_count += batch.count
        if batch.count < MARK_ALL_READ_BATCH_SIZE:
            break
        if batch.last_message_id is None:
            raise RuntimeError("mark-all-read batch did not return its keyset cursor")
        after_message_id = batch.last_message_id
    return MarkAllReadOut(
        success=True,
        count=total_count,
        account_id=str(body.account_id) if body.account_id else None,
        scope_type=scope_type,
        scope_id=scope_id,
    )


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
        except UnaddressableMessageError as exc:
            raise HTTPException(409, str(exc)) from exc
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
    media = _safe_attachment_media_type(payload.content_type)
    # Stream-decrypt chunk by chunk; never materialise the whole attachment.
    return StreamingResponse(payload.open_stream(), media_type=media, headers=headers)


@router.get("/attachments/by-path/{path:path}", include_in_schema=False)
def api_get_attachment_by_path_rejected(path: str):
    """Explicitly reject path-shaped attachment access (architecture M5)."""
    raise HTTPException(400, "attachment access by filesystem path is forbidden; use attachment UUID")
