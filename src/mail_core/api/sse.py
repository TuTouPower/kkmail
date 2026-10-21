"""SSE endpoint with Last-Event-ID replay (architecture §13)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from mail_core.db.session import get_session_factory
from mail_core.realtime.dispatcher import get_dispatcher
from mail_core.realtime.outbox import fetch_since, head_event_id, to_item

log = logging.getLogger("mail_core.api.sse")
router = APIRouter()

# If client Last-Event-ID is older than this many events behind head, send resync hint.
RESYNC_GAP = 500
# Replay page size must be >= RESYNC_GAP so a full page implies a true gap, not truncation.
REPLAY_LIMIT = RESYNC_GAP

# Soft cap on concurrent SSE streams per process (503 when exceeded).
MAX_SSE_CONNECTIONS = int(os.environ.get("MAIL_CORE_SSE_MAX_CONNECTIONS", "128"))
_sse_active = 0
_sse_active_lock = threading.Lock()


def _format_sse(event_id: int, event: str, data: dict) -> str:
    return f"id: {event_id}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass(frozen=True, slots=True)
class _ReplayPlan:
    frames: list[tuple[int, str, dict[str, Any]]]
    cursor: int


class BoundedSet:
    """Fixed-capacity set to dedupe stream events without unbounded memory growth."""

    def __init__(self, maxsize: int = 1000) -> None:
        self.maxsize = maxsize
        self._set: set[int] = set()
        self._order: deque[int] = deque()

    def add(self, item: int) -> None:
        if item in self._set:
            return
        self._set.add(item)
        self._order.append(item)
        if len(self._order) > self.maxsize:
            old = self._order.popleft()
            self._set.discard(old)

    def __contains__(self, item: int) -> bool:
        return item in self._set


def _build_replay(cursor: int, account_id: UUID | None, *, malformed: bool) -> _ReplayPlan:
    """Synchronous DB work for SSE replay — run via ``asyncio.to_thread``."""
    Session = get_session_factory()
    frames: list[tuple[int, str, dict[str, Any]]] = []
    cursor_local = cursor
    with Session() as session:
        head = head_event_id(session)

        if malformed:
            payload = {"reason": "malformed_last_event_id", "head": head}
            frames.append((head, "client.resync_hint", payload))
            return _ReplayPlan(frames=frames, cursor=head)

        if cursor > head:
            payload = {"reason": "cursor_ahead", "head": head, "last_event_id": cursor}
            frames.append((head, "client.resync_hint", payload))
            return _ReplayPlan(frames=frames, cursor=head)

        if cursor > 0 and head - cursor > RESYNC_GAP:
            payload = {"reason": "gap_too_large", "head": head, "last_event_id": cursor}
            frames.append((head, "client.resync_hint", payload))
            return _ReplayPlan(frames=frames, cursor=head)

        rows = fetch_since(
            session,
            last_event_id=cursor,
            limit=REPLAY_LIMIT,
            account_id=account_id,
        )
        seen: set[int] = set()
        for row in rows:
            item = to_item(row)
            # Extra guard: other accounts only (globals have account_id None).
            if account_id and item.account_id and item.account_id != str(account_id):
                continue
            if item.id in seen:
                continue
            frames.append((item.id, item.event_type, item.payload))
            seen.add(item.id)
            cursor_local = item.id
        if len(rows) >= REPLAY_LIMIT and cursor_local < head:
            payload = {
                "reason": "replay_truncated",
                "head": head,
                "last_event_id": cursor_local,
                "replay_limit": REPLAY_LIMIT,
            }
            frames.append((head, "client.resync_hint", payload))
            cursor_local = head
    return _ReplayPlan(frames=frames, cursor=cursor_local)


def _acquire_sse_slot() -> bool:
    global _sse_active
    with _sse_active_lock:
        if _sse_active >= MAX_SSE_CONNECTIONS:
            return False
        _sse_active += 1
        return True


def _release_sse_slot() -> None:
    global _sse_active
    with _sse_active_lock:
        _sse_active = max(0, _sse_active - 1)


@asynccontextmanager
async def sse_connection_slot() -> AsyncIterator[bool]:
    """Acquire an active SSE connection slot for the generator lifetime."""
    acquired = _acquire_sse_slot()
    try:
        yield acquired
    finally:
        if acquired:
            _release_sse_slot()


@router.get(
    "/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE event stream"}},
)
async def stream_events(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after: int | None = Query(default=None, description="Same as Last-Event-ID, for EventSource polyfills"),
    account_id: UUID | None = Query(default=None),
):
    """Server-Sent Events stream. Subscribe first, replay, then live-tail (dedupe by eid)."""

    cursor = 0
    malformed = False
    raw = last_event_id or (str(after) if after is not None else None)
    if raw:
        try:
            cursor = int(raw)
        except ValueError:
            malformed = True
            cursor = 0

    with _sse_active_lock:
        if _sse_active >= MAX_SSE_CONNECTIONS:
            return JSONResponse(
                {"detail": "too many sse connections", "max": MAX_SSE_CONNECTIONS},
                status_code=503,
            )

    async def gen() -> AsyncIterator[str]:
        async with sse_connection_slot() as acquired:
            if not acquired:
                return
            # Subscribe BEFORE replay so events committed during replay land in the queue
            # and are not lost between DB read and live-tail. Dedupe by event id below.
            dispatcher = get_dispatcher()
            queue = dispatcher.subscribe(account_id=str(account_id) if account_id else None)
            seen = BoundedSet(maxsize=1000)
            cursor_local = cursor
            try:
                plan = await asyncio.to_thread(_build_replay, cursor, account_id, malformed=malformed)
                for eid, etype, data in plan.frames:
                    yield _format_sse(eid, etype, data)
                    seen.add(eid)
                cursor_local = plan.cursor

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
                    # Account filter: keep globals (NULL account_id) for account streams.
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
