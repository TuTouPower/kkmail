"""Mail read APIs: unified inbox, folder stats, search."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from mail_core.db.session import get_session_factory
from mail_core.mail.application.queries import (
    get_folder_stats,
    list_folder_stats_for_account,
    unified_inbox,
)
from mail_core.search.index import search_messages

router = APIRouter(prefix="/api/mail", tags=["mail"])


class MessageOut(BaseModel):
    id: str
    account_id: str
    subject: str
    from_address: str
    from_name: str | None
    sort_time: datetime
    is_read: bool
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
):
    Session = get_session_factory()
    with Session() as session:
        page = unified_inbox(
            session,
            account_ids=[account_id] if account_id else None,
            limit=limit,
            cursor_sort_time=cursor_sort_time,
            cursor_message_id=cursor_message_id,
        )
        return PageOut(
            items=[
                MessageOut(
                    id=str(i.id),
                    account_id=str(i.account_id),
                    subject=i.subject,
                    from_address=i.from_address,
                    from_name=i.from_name,
                    sort_time=i.sort_time,
                    is_read=i.is_read,
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
        ids = search_messages(
            session,
            account_ids=[account_id] if account_id else None,
            query=q,
            limit=limit,
        )
        return {"query": q, "message_ids": [str(i) for i in ids]}
