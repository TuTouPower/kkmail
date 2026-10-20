"""SSE endpoint with Last-Event-ID replay (architecture §13)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import OutboxEvent
from mail_core.realtime.dispatcher import get_dispatcher
from mail_core.realtime.outbox import fetch_since, to_item

log = logging.getLogger("mail_core.api.sse")
router = APIRouter()

# If client Last-Event-ID is older than this many events behind head, send resync hint.
RESYNC_GAP = 500


def _format_sse(event_id: int, event: str, data: dict) -> str:
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/events")
async def stream_events(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after: int | None = Query(default=None, description="Same as Last-Event-ID, for EventSource polyfills"),
    account_id: UUID | None = Query(default=None),
):
    """Server-Sent Events stream. Replay from Last-Event-ID then live-tail."""

    cursor = 0
    raw = last_event_id or (str(after) if after is not None else None)
    if raw:
        try:
            cursor = int(raw)
        except ValueError:
            cursor = 0

    async def gen() -> AsyncIterator[str]:
        Session = get_session_factory()
        # Gap check → resync hint
        with Session() as session:
            head = session.scalar(select(func.max(OutboxEvent.id))) or 0
            if cursor > 0 and head - cursor > RESYNC_GAP:
                payload = {"reason": "gap_too_large", "head": head, "last_event_id": cursor}
                yield _format_sse(head, "client.resync_hint", payload)
                cursor_local = head
            else:
                rows = fetch_since(session, last_event_id=cursor, limit=200, account_id=account_id)
                cursor_local = cursor
                for row in rows:
                    item = to_item(row)
                    if account_id and item.account_id and item.account_id != str(account_id):
                        continue
                    yield _format_sse(item.id, item.event_type, item.payload)
                    cursor_local = item.id

        dispatcher = get_dispatcher()
        queue = dispatcher.subscribe(account_id=str(account_id) if account_id else None)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # Comment keepalive only. Dispatch is owned by the LISTEN thread
                    # (single dispatcher; no per-connection polling / dual dispatch).
                    yield ": keepalive\n\n"
                    continue
                if account_id and event.get("account_id") and event["account_id"] != str(account_id):
                    continue
                eid = int(event["id"])
                if eid <= cursor_local:
                    continue
                yield _format_sse(eid, event["event"], event.get("data") or {})
                cursor_local = eid
        finally:
            dispatcher.unsubscribe(queue, account_id=str(account_id) if account_id else None)

    return StreamingResponse(gen(), media_type="text/event-stream")
