"""SSE endpoint with Last-Event-ID replay (architecture §13)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse
from mail_core.db.session import get_session_factory
from mail_core.realtime.dispatcher import get_dispatcher
from mail_core.realtime.outbox import fetch_since, head_event_id, to_item

log = logging.getLogger("mail_core.api.sse")
router = APIRouter()

# If client Last-Event-ID is older than this many events behind head, send resync hint.
RESYNC_GAP = 500
# Replay page size must be >= RESYNC_GAP so a full page implies a true gap, not truncation.
REPLAY_LIMIT = RESYNC_GAP


def _format_sse(event_id: int, event: str, data: dict) -> str:
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/events")
async def stream_events(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after: int | None = Query(default=None, description="Same as Last-Event-ID, for EventSource polyfills"),
    account_id: UUID | None = Query(default=None),
):
    """Server-Sent Events stream. Subscribe first, replay, then live-tail (dedupe by eid)."""

    cursor = 0
    raw = last_event_id or (str(after) if after is not None else None)
    if raw:
        try:
            cursor = int(raw)
        except ValueError:
            cursor = 0

    async def gen() -> AsyncIterator[str]:
        # Subscribe BEFORE replay so events committed during replay land in the queue
        # and are not lost between DB read and live-tail. Dedupe by event id below.
        dispatcher = get_dispatcher()
        queue = dispatcher.subscribe(account_id=str(account_id) if account_id else None)
        seen: set[int] = set()
        cursor_local = cursor
        try:
            Session = get_session_factory()
            with Session() as session:
                head = head_event_id(session)
                if cursor > 0 and head - cursor > RESYNC_GAP:
                    payload = {"reason": "gap_too_large", "head": head, "last_event_id": cursor}
                    yield _format_sse(head, "client.resync_hint", payload)
                    cursor_local = head
                    seen.add(head)
                else:
                    rows = fetch_since(
                        session,
                        last_event_id=cursor,
                        limit=REPLAY_LIMIT,
                        account_id=account_id,
                    )
                    for row in rows:
                        item = to_item(row)
                        if account_id and item.account_id and item.account_id != str(account_id):
                            continue
                        if item.id in seen:
                            continue
                        yield _format_sse(item.id, item.event_type, item.payload)
                        seen.add(item.id)
                        cursor_local = item.id
                    # Full page with more events behind head → client must resync (avoid silent truncate).
                    if len(rows) >= REPLAY_LIMIT and cursor_local < head:
                        payload = {
                            "reason": "replay_truncated",
                            "head": head,
                            "last_event_id": cursor_local,
                            "replay_limit": REPLAY_LIMIT,
                        }
                        yield _format_sse(head, "client.resync_hint", payload)
                        cursor_local = head
                        seen.add(head)

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
                if eid in seen or eid <= cursor_local:
                    continue
                yield _format_sse(eid, event["event"], event.get("data") or {})
                seen.add(eid)
                cursor_local = eid
        finally:
            dispatcher.unsubscribe(queue, account_id=str(account_id) if account_id else None)

    return StreamingResponse(gen(), media_type="text/event-stream")
