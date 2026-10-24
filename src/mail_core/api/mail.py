"""Mail read/mutation API: unified inbox, folder stats, search, detail, flags, trash, attachments.

Routes call the application layer only (queries / search / mutations / attachments).
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mail_core.api.http_headers import content_disposition_attachment
from mail_core.db.session import get_session_factory
from mail_core.accounts import account_ids_for_group
from mail_core.mail.domain.archive import apply_transition
from mail_core.mail.domain.enums import ArchiveState, JobType
from mail_core.mail.storage.models import Message, MessageArchiveState
from mail_core.sync.jobs import enqueue_job
from mail_core.security.redact import safe_error
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
    MessageListItem,
    account_emails_by_id,
    get_folder_stats,
    get_message_detail,
    list_folder_stats_for_account,
    query_global_inbox_stats,
    query_group_inbox_stats,
    unified_inbox,
)
from mail_core.mail.application.search import search_messages_page

log = logging.getLogger("mail_core.api.mail")
router = APIRouter(prefix="/api/mail", tags=["mail"])


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
    attachments: list[AttachmentOut]


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


class MutationOut(BaseModel):
    id: str
    account_id: str
    operation_id: str | None = None
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
        return query_global_inbox_stats(session)


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
        d = get_message_detail(session, message_id)
        if d is None:
            raise HTTPException(404, "message not found")
        st = session.get(MessageArchiveState, message_id)
        msg = session.get(Message, message_id)
        is_archived = (st.state == ArchiveState.ARCHIVE_COMPLETE.value) if st is not None else None
        # AC-001: 若邮件正文未就绪且未解析失败，提升归档优先级至最高 (0) 并入队高优归档任务 (priority=10)
        if (
            is_archived is False
            and msg is not None
            and msg.remote_id
            and msg.remote_id.strip()
            and not d.parse_error
        ):
            if st is not None and st.state in (
                ArchiveState.METADATA_SYNCED.value,
                ArchiveState.ARCHIVE_PENDING.value,
            ):
                st.priority = 0
                if st.state == ArchiveState.METADATA_SYNCED.value:
                    apply_transition(st, ArchiveState.ARCHIVE_PENDING)
                enqueue_job(
                    session,
                    job_type=JobType.ARCHIVE_MIME_BATCH.value,
                    account_id=d.account_id,
                    payload={"message_id": str(message_id), "batch_size": 1},
                    priority=10,
                    dedupe_key=f"archive_msg:{message_id}",
                )
                session.commit()
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
            body=d.body,
            body_type=d.body_type,
            parse_error=d.parse_error,
            is_archived=is_archived,
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


@router.post("/messages/{message_id}/sync-body", response_model=MessageDetailOut, response_model_by_alias=True)
def api_sync_message_body(message_id: UUID) -> MessageDetailOut:
    """Trigger on-demand highest-priority body sync for a message."""
    Session = get_session_factory()
    with Session() as session:
        msg = session.get(Message, message_id)
        if msg is None:
            raise HTTPException(404, "message not found")
        if not msg.remote_id or not msg.remote_id.strip():
            raise HTTPException(409, "message has no verified provider remote id")
        account_id = msg.account_id
        st = session.get(MessageArchiveState, message_id)
        if st is not None:
            st.priority = 0
            if st.state == ArchiveState.METADATA_SYNCED.value:
                apply_transition(st, ArchiveState.ARCHIVE_PENDING)
            enqueue_job(
                session,
                job_type=JobType.ARCHIVE_MIME_BATCH.value,
                account_id=account_id,
                payload={"message_id": str(message_id), "batch_size": 1},
                priority=10,
                dedupe_key=f"archive_msg:{message_id}",
            )
            session.commit()

    # 尝试就地执行单封归档以提供即时响应
    from mail_core.blobs.archive import run_archive_batch
    attempt_id = uuid.uuid4().hex[:12]
    worker_id = f"api-on-demand:{attempt_id}"
    t0 = time.monotonic()
    log.info(
        "api_sync_message_body start attempt=%s account_id=%s message_id=%s",
        attempt_id,
        account_id,
        message_id,
    )
    try:
        run_res = run_archive_batch(
            account_id=account_id,
            worker_id=worker_id,
            payload={"message_id": str(message_id), "batch_size": 1},
        )
    except Exception as exc:
        log.warning("on-demand sync error attempt=%s for message %s: %s", attempt_id, message_id, safe_error(exc))
        run_res = {"status": "error", "error": safe_error(exc)}

    elapsed_ms = (time.monotonic() - t0) * 1000
    log.info(
        "api_sync_message_body end attempt=%s message_id=%s elapsed_ms=%.1f result=%s",
        attempt_id,
        message_id,
        elapsed_ms,
        run_res,
    )

    with Session() as session:
        d = get_message_detail(session, message_id)
        if d is None:
            raise HTTPException(404, "message not found")
        st = session.get(MessageArchiveState, message_id)
        is_archived = (st.state == ArchiveState.ARCHIVE_COMPLETE.value) if st is not None else None
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
            body=d.body,
            body_type=d.body_type,
            parse_error=d.parse_error,
            is_archived=is_archived,
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
    media = payload.content_type or "application/octet-stream"
    # Stream-decrypt chunk by chunk; never materialise the whole attachment.
    return StreamingResponse(payload.open_stream(), media_type=media, headers=headers)


@router.get("/attachments/by-path/{path:path}", include_in_schema=False)
def api_get_attachment_by_path_rejected(path: str):
    """Explicitly reject path-shaped attachment access (architecture M5)."""
    raise HTTPException(400, "attachment access by filesystem path is forbidden; use attachment UUID")
