"""Mail read APIs: unified inbox, folder stats, search."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from mail_core.mail.application.attachments import (
    AttachmentAccessError,
    PathTraversalRejected,
    load_attachment,
)
from mail_core.db.session import get_session_factory
from mail_core.mail.application.mutations import set_message_flagged, set_message_read, trash_message
from mail_core.api.http_headers import content_disposition_attachment
from mail_core.mail.application.queries import (
    account_emails_by_id,
    get_folder_stats,
    get_message_detail,
    list_folder_stats_for_account,
    resolve_account_id_by_email,
    unified_inbox,
)
from mail_core.mail.application.search import search_message_ids

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
    is_flagged: bool = False
    has_attachments: bool
    snippet: str | None
    folder_id: str | None


class PageOut(BaseModel):
    items: list[MessageOut]
    next_cursor: dict | None


@router.get("/inbox", response_model=PageOut)
def api_unified_inbox(
    limit: int = Query(50, ge=1, le=200),
    cursor_sort_time: datetime | None = None,
    cursor_message_id: UUID | None = None,
    account_id: UUID | None = None,
    account_email: str | None = Query(None, description="Filter by account email (preferred over Flask numeric ids)"),
):
    Session = get_session_factory()
    with Session() as session:
        resolved = account_id
        if resolved is None and account_email:
            resolved = resolve_account_id_by_email(session, account_email)
            if resolved is None:
                return PageOut(items=[], next_cursor=None)
        page = unified_inbox(
            session,
            account_ids=[resolved] if resolved else None,
            limit=limit,
            cursor_sort_time=cursor_sort_time,
            cursor_message_id=cursor_message_id,
        )
        emails = account_emails_by_id(session, [i.account_id for i in page.items])
        return PageOut(
            items=[
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
                for i in page.items
            ],
            next_cursor=page.next_cursor,
        )


@router.get("/accounts/{account_id}/folder-stats")
def api_folder_stats(account_id: UUID):
    Session = get_session_factory()
    with Session() as session:
        return {"account_id": str(account_id), "folders": list_folder_stats_for_account(session, account_id)}


@router.get("/folders/{folder_id}/stats")
def api_one_folder_stats(folder_id: UUID):
    Session = get_session_factory()
    with Session() as session:
        stats = get_folder_stats(session, folder_id)
        if stats is None:
            raise HTTPException(404, "folder stats not found")
        return {
            "folder_id": str(folder_id),
            "total_count": stats.total_count,
            "unread_count": stats.unread_count,
            "updated_at": stats.updated_at.isoformat() if stats.updated_at else None,
        }


@router.get("/search")
def api_search(q: str = Query(..., min_length=1), account_id: UUID | None = None, limit: int = Query(50, ge=1, le=200)):
    Session = get_session_factory()
    with Session() as session:
        ids = search_message_ids(
            session,
            account_ids=[account_id] if account_id else None,
            query=q,
            limit=limit,
        )
        return {"query": q, "message_ids": [str(i) for i in ids]}

@router.get("/messages/{message_id}")
def api_get_message(message_id: UUID):
    """Message metadata + parsed body + attachments (by UUID)."""
    Session = get_session_factory()
    with Session() as session:
        detail = get_message_detail(session, message_id)
        if detail is None:
            raise HTTPException(404, "message not found")
        body = detail.body_html if detail.body_type == "html" else (detail.body_text or "")
        return {
            "id": str(detail.id),
            "account_id": str(detail.account_id),
            "subject": detail.subject,
            "from_address": detail.from_address,
            "from_name": detail.from_name,
            "from": (f"{detail.from_name} <{detail.from_address}>" if detail.from_name else detail.from_address),
            "to": ", ".join(str(x) for x in detail.to_addresses) if detail.to_addresses else "",
            "cc": ", ".join(str(x) for x in detail.cc_addresses) if detail.cc_addresses else "",
            "date": detail.sort_time.isoformat(),
            "is_read": detail.is_read,
            "has_attachments": detail.has_attachments,
            "snippet": detail.snippet,
            "body": body,
            "body_type": detail.body_type,
            "parse_error": detail.parse_error,
            "attachments": [
                {
                    "id": str(a.id),
                    "name": a.filename,
                    "contentType": a.content_type,
                    "size": a.size_bytes,
                    "is_inline": a.is_inline,
                }
                for a in detail.attachments
            ],
        }


@router.get("/messages/{message_id}/body")
def api_get_message_body(message_id: UUID):
    """Body-only view for the reader (same source as GET /messages/{id})."""
    Session = get_session_factory()
    with Session() as session:
        detail = get_message_detail(session, message_id)
        if detail is None:
            raise HTTPException(404, "message not found")
        body = detail.body_html if detail.body_type == "html" else (detail.body_text or "")
        return {
            "id": str(detail.id),
            "body": body,
            "body_type": detail.body_type,
            "parse_error": detail.parse_error,
            "snippet": detail.snippet,
        }




class ReadBody(BaseModel):
    is_read: bool = True


class FlagBody(BaseModel):
    is_flagged: bool = True


@router.post("/messages/{message_id}/read")
def api_set_message_read(message_id: UUID, body: ReadBody | None = None):
    """Local-first mark read/unread + enqueue remote_operations mark_read."""
    want = True if body is None else bool(body.is_read)
    Session = get_session_factory()
    with Session() as session:
        try:
            result = set_message_read(session, message_id, is_read=want)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        session.commit()
        return {
            "id": str(result.message_id),
            "account_id": str(result.account_id),
            "operation_id": str(result.operation_id),
            "is_read": result.is_read,
        }


@router.post("/messages/{message_id}/flag")
def api_set_message_flag(message_id: UUID, body: FlagBody | None = None):
    """Local-first flag/unflag + enqueue remote_operations set_flag."""
    want = True if body is None else bool(body.is_flagged)
    Session = get_session_factory()
    with Session() as session:
        try:
            result = set_message_flagged(session, message_id, is_flagged=want)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        session.commit()
        return {
            "id": str(result.message_id),
            "account_id": str(result.account_id),
            "operation_id": str(result.operation_id),
            "is_flagged": result.is_flagged,
        }



@router.post("/messages/{message_id}/trash")
def api_trash_message(message_id: UUID):
    """Local-first trash + enqueue remote_operations trash."""
    Session = get_session_factory()
    with Session() as session:
        try:
            result = trash_message(session, message_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        session.commit()
        return {
            "id": str(result.message_id),
            "account_id": str(result.account_id),
            "operation_id": str(result.operation_id),
            "success": True,
        }


@router.get("/attachments/{attachment_id}")
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
        }
        media = payload.content_type or "application/octet-stream"
        return Response(content=payload.data, media_type=media, headers=headers)


@router.get("/attachments/by-path/{path:path}")
def api_get_attachment_by_path_rejected(path: str):
    """Explicitly reject path-shaped attachment access (architecture M5)."""
    raise HTTPException(
        400,
        "attachment access by filesystem path is forbidden; use attachment UUID",
    )
