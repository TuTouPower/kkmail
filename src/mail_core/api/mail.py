"""Mail read/mutation API: unified inbox, folder stats, search, detail, flags, trash, attachments.

Routes call the application layer only (queries / search / mutations / attachments).
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import datetime
from email.utils import formataddr, getaddresses
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from mail_core.api.http_headers import content_disposition_attachment
from mail_core.db.session import get_session_factory
from mail_core.accounts import enabled_account_ids
from mail_core.mail.application.sync_requests import (
    SyncRequestOut,
    get_sync_request_report,
    list_recent_sync_requests,
    record_account_activity,
)
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
    MessageHasNoProviderRemoteId,
    get_message_detail_with_archive_status,
    sync_message_body,
)
from mail_core.mail.application.search import (
    SearchPage,
    search_message_ids,
    search_messages_page,
)
from mail_core.mail.application.remote_images import (
    InvalidSenderEmailError,
    allow_message_remote_images,
    allow_sender_remote_images,
    is_remote_images_allowed,
    list_allowed_senders,
    normalize_sender_email,
    remove_allowed_sender,
)
from mail_core.mail.storage.models import (
    Attachment,
    Message,
    MessageArchiveState,
)
from mail_core.security.inline_preview import (
    build_inline_image_preview_url,
    is_supported_inline_image_mime,
    verify_inline_image_preview_token,
)

router = APIRouter(prefix="/api/mail", tags=["mail"])
preview_router = APIRouter(prefix="/api/mail", tags=["preview"])
_MEDIA_TYPE_TOKEN = r"[A-Za-z0-9!#$%&'*+.^_`|~-]+"
_MEDIA_TYPE_PATTERN = re.compile(rf"{_MEDIA_TYPE_TOKEN}/{_MEDIA_TYPE_TOKEN}", re.ASCII)


def _safe_attachment_media_type(value: str | None) -> str:
    if value and _MEDIA_TYPE_PATTERN.fullmatch(value):
        return value
    return "application/octet-stream"


class MessageFolderLocationOut(BaseModel):
    folder_id: str
    role: str


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
    locations: list[MessageFolderLocationOut]


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
    content_id: str | None = None
    preview_url: str | None = None


class MessageEmailAddressOut(BaseModel):
    name: str | None
    address: str | None
    text: str | None = None


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
    to_addresses: list[MessageEmailAddressOut]
    cc_addresses: list[MessageEmailAddressOut]
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
    remote_images_allowed: bool = False
    can_allow_sender: bool = False
    attachments: list[AttachmentOut]


class SenderAllowIn(BaseModel):
    message_id: UUID


class SenderRemoteImageAllowOut(BaseModel):
    id: str
    from_address: str
    created_at: datetime


class RemoteImagesAllowedOut(BaseModel):
    success: bool = True
    remote_images_allowed: bool = True


def _is_reliable_email_address(value: str) -> bool:
    if not value or any(character.isspace() or character in "<>,;" for character in value):
        return False
    if value.count("@") != 1:
        return False
    local, domain = value.split("@", 1)
    local_punctuation = "!#$%&'*+-/=?^_`{|}~."
    if (
        not local
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or any(not (character.isalnum() or character in local_punctuation) for character in local)
        or len(domain) > 253
    ):
        return False
    labels = domain.split(".")
    return bool(labels) and all(
        label
        and len(label) <= 63
        and label[0].isalnum()
        and label[-1].isalnum()
        and all(character.isalnum() or character == "-" for character in label)
        for label in labels
    )


def _recipient_addresses(values: list[object]) -> list[MessageEmailAddressOut]:
    result: list[MessageEmailAddressOut] = []
    for value in values:
        raw = "" if value is None else str(value).strip()
        if not raw:
            continue
        try:
            parsed = getaddresses([raw])
        except (TypeError, ValueError):
            parsed = []
        reliable = [
            (name.strip() or None, address.strip())
            for name, address in parsed
            if _is_reliable_email_address(address.strip())
        ]
        if not reliable:
            result.append(MessageEmailAddressOut(name=None, address=None, text=raw))
            continue
        reliable_set = set(reliable)
        for name, address in parsed:
            normalized_name = name.strip() or None
            normalized_address = address.strip()
            if (normalized_name, normalized_address) in reliable_set:
                result.append(MessageEmailAddressOut(name=normalized_name, address=normalized_address))
            else:
                text = formataddr((name, address)).strip() or raw
                result.append(MessageEmailAddressOut(name=None, address=None, text=text))
    return result


MAX_INLINE_PREVIEWS_PER_MESSAGE = 50


def _detail_out(
    detail: MessageDetail,
    is_archived: bool | None,
    archive_state: str | None = None,
    archive_has_error: bool = False,
    remote_images_allowed: bool = False,
    can_allow_sender: bool = False,
) -> MessageDetailOut:
    signed_count = 0
    att_outs: list[AttachmentOut] = []
    for attachment in detail.attachments:
        preview_url = None
        if attachment.is_inline and is_supported_inline_image_mime(attachment.content_type):
            if signed_count < MAX_INLINE_PREVIEWS_PER_MESSAGE:
                preview_url = build_inline_image_preview_url(str(attachment.id))
                signed_count += 1
        att_outs.append(
            AttachmentOut(
                id=str(attachment.id),
                name=attachment.filename,
                contentType=attachment.content_type,
                size=attachment.size_bytes,
                is_inline=attachment.is_inline,
                content_id=attachment.content_id,
                preview_url=preview_url,
            )
        )

    return MessageDetailOut(
        id=str(detail.id),
        account_id=str(detail.account_id),
        subject=detail.subject,
        from_address=detail.from_address,
        from_name=detail.from_name,
        from_=(f"{detail.from_name} <{detail.from_address}>" if detail.from_name else detail.from_address),
        to=", ".join(str(value) for value in detail.to_addresses) if detail.to_addresses else "",
        cc=", ".join(str(value) for value in detail.cc_addresses) if detail.cc_addresses else "",
        to_addresses=_recipient_addresses(detail.to_addresses),
        cc_addresses=_recipient_addresses(detail.cc_addresses),
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
        remote_images_allowed=remote_images_allowed,
        can_allow_sender=can_allow_sender,
        attachments=att_outs,
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
    job_id: str | None = None
    status: Literal["queued", "in_progress", "complete"]


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
            locations=[
                MessageFolderLocationOut(folder_id=str(location.folder_id), role=location.role)
                for location in i.locations
            ],
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
            if group_id is not None:
                account_ids = enabled_account_ids(session, group_id)
            elif account_id is not None:
                account_ids = [account_id]
            elif folder_id is None:
                account_ids = enabled_account_ids(session)
            else:
                account_ids = None
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
            if group_id is not None:
                account_ids = enabled_account_ids(session, group_id)
            elif account_id is not None:
                account_ids = [account_id]
            elif folder_id is None:
                account_ids = enabled_account_ids(session)
            else:
                account_ids = None
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
        detail, is_archived = result
        state = session.get(MessageArchiveState, message_id)
        allowed = is_remote_images_allowed(session, message_id, detail.from_address)
        try:
            normalize_sender_email(detail.from_address)
            can_allow = True
        except InvalidSenderEmailError:
            can_allow = False
        return _detail_out(
            detail,
            is_archived,
            archive_state=state.state if state is not None else None,
            archive_has_error=bool(state and state.last_error),
            remote_images_allowed=allowed,
            can_allow_sender=can_allow,
        )


@router.post(
    "/messages/{message_id}/sync-body",
    response_model=SyncBodyAcceptedOut,
    response_model_by_alias=True,
    status_code=202,
)
def api_sync_message_body(message_id: UUID, response: Response) -> SyncBodyAcceptedOut:
    """Queue an on-demand highest-priority body sync for a message."""
    try:
        result = sync_message_body(message_id)
    except MessageHasNoProviderRemoteId as exc:
        raise HTTPException(409, str(exc)) from exc
    except MessageArchiveStateUnavailable as exc:
        raise HTTPException(409, str(exc)) from exc
    if result is None:
        raise HTTPException(404, "message not found")
    if result.status == "complete":
        response.status_code = 200
    else:
        response.status_code = 202
    return SyncBodyAcceptedOut(
        message_id=str(result.message_id),
        job_id=str(result.job_id) if result.job_id else None,
        status=result.status,  # type: ignore[arg-type]
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


# A180: hard budgets for the mark-all-read batch loop. Each batch commits
# independently, so the operation is NOT atomic: on error or budget
# exhaustion, batches already committed stay applied. Retrying is safe —
# the operation is idempotent and resumes from the remaining unread set.
MARK_ALL_READ_MAX_BATCHES = 200
MARK_ALL_READ_MAX_SECONDS = 120.0


@router.post("/mark-all-read", response_model=MarkAllReadOut)
def api_mark_all_read(body: MarkAllReadBody) -> MarkAllReadOut:
    """Batch mark messages read across the matching scope (folder/account/flag).

    Non-atomic by design: batches commit independently, so a failure may
    leave partial progress applied. The request is idempotent — retry it
    to continue marking the remainder.
    """
    Session = get_session_factory()
    if body.group_id is not None and (body.account_id is not None or body.folder_id is not None):
        raise HTTPException(400, "group_id cannot be combined with account_id or folder_id")
    scope_account_ids = None
    if body.group_id is not None:
        with Session() as scope_session:
            try:
                scope_account_ids = enabled_account_ids(scope_session, body.group_id)
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc
    elif body.account_id is None and body.folder_id is None:
        with Session() as scope_session:
            scope_account_ids = enabled_account_ids(scope_session)
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
    batches_done = 0
    started_at = time.monotonic()
    while True:
        if batches_done >= MARK_ALL_READ_MAX_BATCHES or (
            time.monotonic() - started_at > MARK_ALL_READ_MAX_SECONDS
        ):
            raise HTTPException(
                500,
                "mark-all-read exceeded its batch/time budget; batches already "
                "committed stay applied — retry to continue (idempotent)",
            )
        with Session() as session:
            try:
                batch = mark_all_messages_read(
                    session,
                    account_id=body.account_id,
                    folder_role=body.folder_role,
                    folder_id=body.folder_id,
                    is_flagged=body.is_flagged,
                    group_id=body.group_id if scope_account_ids is None else None,
                    account_ids=scope_account_ids,
                    after_message_id=after_message_id,
                    limit=MARK_ALL_READ_BATCH_SIZE,
                )
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc
            session.commit()
        batches_done += 1
        total_count += batch.count
        if batch.count < MARK_ALL_READ_BATCH_SIZE:
            break
        if batch.last_message_id is None:
            raise RuntimeError("mark-all-read batch did not return its keyset cursor")
        if after_message_id is not None and batch.last_message_id <= after_message_id:
            raise HTTPException(
                500,
                "mark-all-read cursor did not advance; batches already committed "
                "stay applied — retry to continue (idempotent)",
            )
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


class ActivityIn(BaseModel):
    account_ids: list[UUID] = Field(default_factory=list)


@router.get("/sync/requests", response_model=list[SyncRequestOut])
def api_list_sync_requests(
    account_id: UUID | None = None,
    group_id: UUID | None = None,
    folder_id: UUID | None = None,
    folder_role: str | None = None,
    limit: int = 50,
) -> list[SyncRequestOut]:
    """Recent unfinished requests for a scope (progress recovery, design §6)."""
    Session = get_session_factory()
    with Session() as session:
        return list_recent_sync_requests(
            session,
            account_id=account_id,
            group_id=group_id,
            folder_id=folder_id,
            folder_role=folder_role,
            limit=limit,
        )


@router.get("/sync/requests/{request_id}", response_model=SyncRequestOut)
def api_get_sync_request(request_id: UUID) -> SyncRequestOut:
    Session = get_session_factory()
    with Session() as session:
        report = get_sync_request_report(session, request_id)
        if report is None:
            raise HTTPException(404, "sync request not found")
        return report


@router.post("/sync/activity", status_code=204)
def api_report_sync_activity(body: ActivityIn) -> Response:
    Session = get_session_factory()
    with Session() as session:
        record_account_activity(session, body.account_ids)
        session.commit()
    return Response(status_code=204)


# --- Remote image allowlists and inline preview (t066) ---


@router.post("/messages/{message_id}/allow-remote-images", response_model=RemoteImagesAllowedOut)
def api_allow_message_remote_images(message_id: UUID) -> RemoteImagesAllowedOut:
    """Allow remote images for a single message permanently in DB."""
    Session = get_session_factory()
    with Session() as session:
        try:
            allow_message_remote_images(session, message_id)
            session.commit()
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
    return RemoteImagesAllowedOut(success=True, remote_images_allowed=True)


def _is_valid_image_magic(first_chunk: bytes, mime: str | None) -> bool:
    if not first_chunk or not mime:
        return False
    mime = mime.strip().lower()
    if mime == "image/png":
        return first_chunk.startswith(b"\x89PNG\r\n\x1a\n")
    if mime == "image/jpeg":
        return first_chunk.startswith(b"\xff\xd8\xff")
    if mime == "image/gif":
        return first_chunk.startswith(b"GIF87a") or first_chunk.startswith(b"GIF89a")
    if mime == "image/webp":
        return len(first_chunk) >= 12 and first_chunk.startswith(b"RIFF") and first_chunk[8:12] == b"WEBP"
    return False


@router.post("/senders/allow-remote-images", response_model=RemoteImagesAllowedOut)
def api_allow_sender_remote_images(body: SenderAllowIn) -> RemoteImagesAllowedOut:
    """Allow remote images globally for a verified sender email."""
    Session = get_session_factory()
    with Session() as session:
        msg = session.get(Message, body.message_id)
        if msg is None:
            raise HTTPException(404, "message not found")
        addr = msg.from_address

        try:
            allow_sender_remote_images(session, addr)
            session.commit()
        except InvalidSenderEmailError as exc:
            raise HTTPException(422, str(exc)) from exc
    return RemoteImagesAllowedOut(success=True, remote_images_allowed=True)


@router.get("/senders/allowed-remote-images", response_model=list[SenderRemoteImageAllowOut])
def api_list_allowed_senders() -> list[SenderRemoteImageAllowOut]:
    """List all allowed senders for remote image rendering."""
    Session = get_session_factory()
    with Session() as session:
        records = list_allowed_senders(session)
        return [
            SenderRemoteImageAllowOut(
                id=str(r.id),
                from_address=r.from_address,
                created_at=r.created_at,
            )
            for r in records
        ]


@router.delete("/senders/allowed-remote-images/{sender_id}", response_model=MutationOut)
def api_remove_allowed_sender(sender_id: UUID) -> MutationOut:
    """Remove a sender from the global remote images allowlist."""
    Session = get_session_factory()
    with Session() as session:
        removed = remove_allowed_sender(session, sender_id)
        if not removed:
            raise HTTPException(404, "Allowed sender not found")
        session.commit()
    return MutationOut(success=True)


@preview_router.api_route(
    "/attachments/{attachment_id}/preview",
    methods=["GET", "HEAD"],
    response_class=StreamingResponse,
    responses={
        200: {"content": {"image/*": {}}},
        400: {"description": "Bad Request"},
        401: {"description": "Invalid or expired preview token"},
        403: {"description": "Forbidden attachment preview"},
        404: {"description": "Attachment not found"},
    },
)
def api_preview_inline_attachment(attachment_id: str, request: Request, token: str = Query(...)):
    """Preview an inline image attachment with a short-lived signed URL token.

    Operates without ambient session cookie to support strict sandbox iframe.
    """
    if not verify_inline_image_preview_token(attachment_id, token):
        raise HTTPException(401, "Invalid or expired preview token")

    Session = get_session_factory()
    with Session() as session:
        try:
            att_uuid = uuid.UUID(attachment_id)
        except (ValueError, TypeError):
            raise HTTPException(400, "invalid attachment UUID")

        att = session.get(Attachment, att_uuid)
        if att is None:
            raise HTTPException(404, "attachment not found")
        if not att.is_inline:
            raise HTTPException(403, "attachment is not inline")
        if not is_supported_inline_image_mime(att.content_type):
            raise HTTPException(403, "unsupported inline image format")

        try:
            payload = load_attachment(session, attachment_id)
        except PathTraversalRejected as exc:
            raise HTTPException(400, str(exc)) from exc
        except AttachmentAccessError as exc:
            raise HTTPException(404, str(exc)) from exc

    stream = payload.open_stream()
    first_chunk = next(stream, b"")
    if not _is_valid_image_magic(first_chunk, att.content_type):
        raise HTTPException(403, "attachment content magic does not match image format")

    headers = {
        "Content-Disposition": "inline",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    if payload.size_bytes is not None:
        headers["X-Attachment-Size"] = str(payload.size_bytes)

    if request.method == "HEAD":
        return Response(status_code=200, media_type=payload.content_type or "application/octet-stream", headers=headers)

    def _safe_stream():
        if first_chunk:
            yield first_chunk
        yield from stream

    return StreamingResponse(
        _safe_stream(),
        media_type=payload.content_type or "application/octet-stream",
        headers=headers,
    )
