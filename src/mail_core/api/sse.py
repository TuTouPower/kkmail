"""SSE endpoint with Last-Event-ID replay (architecture §13)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from mail_core.api.deps import require_auth
from mail_core.db.session import get_session_factory
from mail_core.realtime.dispatcher import SSE_STREAM_CLOSE, get_dispatcher
from mail_core.realtime.outbox import fetch_published_since, pruned_through_seq, publication_head, to_item
from mail_core.security.auth import AuthPrincipal

log = logging.getLogger("mail_core.api.sse")
router = APIRouter()

# If client Last-Event-ID is older than this many events behind head, send resync hint.
RESYNC_GAP = 500
# Replay page size must be >= RESYNC_GAP so a full page implies a true gap, not truncation.
REPLAY_LIMIT = RESYNC_GAP
SESSION_EPOCH_RECHECK_INTERVAL_S = 60.0

# Soft cap on concurrent SSE streams per process (503 when exceeded).
_DEFAULT_SSE_CONNECTIONS = 128
# Cache entry: (raw env value the cap was parsed from, parsed cap).
# Recording the raw value lets an env change take effect without a
# process restart (A244); an unchanged raw value keeps the cache hit.
_sse_max_connections_cache: tuple[str, int] | None = None
_sse_max_connections_lock = threading.Lock()
_sse_active = 0
_sse_active_lock = threading.Lock()


def _max_sse_connections() -> int:
    global _sse_max_connections_cache
    raw = os.environ.get("MAIL_CORE_SSE_MAX_CONNECTIONS", "128")
    cache = _sse_max_connections_cache
    if cache is not None and cache[0] == raw:
        return cache[1]
    with _sse_max_connections_lock:
        cache = _sse_max_connections_cache
        if cache is not None and cache[0] == raw:
            return cache[1]
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value <= 0:
            log.warning(
                "invalid MAIL_CORE_SSE_MAX_CONNECTIONS=%r; using default %s",
                raw,
                _DEFAULT_SSE_CONNECTIONS,
            )
            value = _DEFAULT_SSE_CONNECTIONS
        _sse_max_connections_cache = (raw, value)
        return value


def _get_session_epoch(force_refresh: bool = False) -> int:
    from mail_core.security.auth import get_session_epoch

    return get_session_epoch(force_refresh=force_refresh)


def _format_sse(cursor_id: str, event: str, data: dict) -> str:
    return f"id: {cursor_id}\nevent: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass(frozen=True, slots=True)
class _ReplayPlan:
    frames: list[tuple[str, str, dict[str, Any]]]
    cursor: str
    cursor_seq: int


class BoundedSet:
    """Fixed-capacity set to dedupe stream events without unbounded memory growth."""

    def __init__(self, maxsize: int = 1000) -> None:
        self.maxsize = maxsize
        self._set: set[str] = set()
        self._order: deque[str] = deque()

    def add(self, item: str) -> None:
        if item in self._set:
            return
        self._set.add(item)
        self._order.append(item)
        if len(self._order) > self.maxsize:
            old = self._order.popleft()
            self._set.discard(old)

    def __contains__(self, item: str) -> bool:
        return item in self._set


def _parse_v2_cursor(raw: str | None) -> tuple[str | None, int | None, bool]:
    if not raw:
        return None, None, False
    raw = raw.strip()
    if raw.startswith("v2:"):
        parts = raw.split(":")
        if len(parts) == 3:
            epoch_str, seq_str = parts[1], parts[2]
            try:
                UUID(epoch_str)
                seq = int(seq_str)
                if seq >= 0:
                    return epoch_str, seq, False
            except (ValueError, TypeError):
                pass
    return None, None, True


def _build_replay(raw_cursor: str | None, account_id: UUID | None) -> _ReplayPlan:
    """Synchronous DB work for SSE replay — run via ``asyncio.to_thread``."""
    Session = get_session_factory()
    frames: list[tuple[str, str, dict[str, Any]]] = []
    with Session() as session:
        current_epoch, head_seq = publication_head(session)
        head_cursor = f"v2:{current_epoch}:{head_seq}"

        if not raw_cursor:
            # First connect without cursor: send resync hint with head cursor
            payload = {"reason": "initial_connect", "head": head_cursor}
            frames.append((head_cursor, "client.resync_hint", payload))
            return _ReplayPlan(frames=frames, cursor=head_cursor, cursor_seq=head_seq)

        epoch, seq, malformed = _parse_v2_cursor(raw_cursor)
        if malformed or epoch != current_epoch:
            payload = {"reason": "epoch_mismatch", "head": head_cursor}
            frames.append((head_cursor, "client.resync_hint", payload))
            return _ReplayPlan(frames=frames, cursor=head_cursor, cursor_seq=head_seq)

        assert seq is not None
        if seq > head_seq:
            payload = {"reason": "cursor_ahead", "head": head_cursor, "last_seq": seq}
            frames.append((head_cursor, "client.resync_hint", payload))
            return _ReplayPlan(frames=frames, cursor=head_cursor, cursor_seq=head_seq)

        # Retention gap (design §9.2): the rows after this cursor have been
        # pruned, so no replay — however small the distance to head — can be
        # complete. This check is on the global publication watermark: it
        # applies equally to an empty retention window, account-filtered
        # streams, and consumers that lag far behind.
        pruned_seq = pruned_through_seq(session)
        if seq < pruned_seq:
            payload = {
                "reason": "retention_gap",
                "head": head_cursor,
                "last_seq": seq,
                "pruned_through_seq": pruned_seq,
            }
            frames.append((head_cursor, "client.resync_hint", payload))
            return _ReplayPlan(frames=frames, cursor=head_cursor, cursor_seq=head_seq)

        if head_seq - seq > RESYNC_GAP:
            payload = {"reason": "gap_too_large", "head": head_cursor, "last_seq": seq}
            frames.append((head_cursor, "client.resync_hint", payload))
            return _ReplayPlan(frames=frames, cursor=head_cursor, cursor_seq=head_seq)

        rows = fetch_published_since(
            session,
            after_seq=seq,
            limit=REPLAY_LIMIT,
            account_id=account_id,
        )
        seen: set[str] = set()
        cursor_seq_local = seq
        for row in rows:
            r_seq = int(row.publication_seq or 0)
            cursor_id = f"v2:{current_epoch}:{r_seq}"
            item = to_item(row)
            if account_id and item.account_id and item.account_id != str(account_id):
                continue
            if cursor_id in seen:
                continue
            frames.append((cursor_id, item.event_type, item.payload))
            seen.add(cursor_id)
            cursor_seq_local = max(cursor_seq_local, r_seq)

        final_cursor = f"v2:{current_epoch}:{cursor_seq_local}"
        if len(rows) >= REPLAY_LIMIT and cursor_seq_local < head_seq:
            payload = {
                "reason": "replay_truncated",
                "head": head_cursor,
                "last_seq": cursor_seq_local,
                "replay_limit": REPLAY_LIMIT,
            }
            frames.append((head_cursor, "client.resync_hint", payload))
            final_cursor = head_cursor
            cursor_seq_local = head_seq

        return _ReplayPlan(frames=frames, cursor=final_cursor, cursor_seq=cursor_seq_local)


def _acquire_sse_slot() -> bool:
    global _sse_active
    with _sse_active_lock:
        if _sse_active >= _max_sse_connections():
            return False
        _sse_active += 1
        return True


def _release_sse_slot() -> None:
    global _sse_active
    with _sse_active_lock:
        _sse_active = max(0, _sse_active - 1)


@router.get(
    "/events",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "SSE event stream"}},
)
async def stream_events(
    request: Request,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after: str | None = Query(default=None, description="Same as Last-Event-ID, for EventSource polyfills"),
    account_id: UUID | None = Query(default=None),
    principal: AuthPrincipal = Depends(require_auth),
):
    """Server-Sent Events stream. Subscribe first, replay, then live-tail (dedupe by eid)."""

    session_epoch = principal.session_epoch if principal.via == "session" else None
    raw_cursor = last_event_id or after

    if not _acquire_sse_slot():
        return JSONResponse(
            {"detail": "too many sse connections", "max": _max_sse_connections()},
            status_code=503,
        )

    slot_release_lock = threading.Lock()
    slot_released = False

    def release_slot() -> None:
        nonlocal slot_released
        with slot_release_lock:
            if slot_released:
                return
            slot_released = True
        _release_sse_slot()

    async def gen() -> AsyncIterator[str]:
        dispatcher = None
        queue = None
        try:
            dispatcher = get_dispatcher()
            queue = dispatcher.subscribe(
                account_id=str(account_id) if account_id else None,
                session_epoch=session_epoch,
            )
            seen = BoundedSet(maxsize=1000)
            if session_epoch is not None:
                current_epoch = await asyncio.to_thread(_get_session_epoch, True)
                if current_epoch != session_epoch:
                    return
            next_epoch_recheck = time.monotonic() + SESSION_EPOCH_RECHECK_INTERVAL_S
            plan = await asyncio.to_thread(_build_replay, raw_cursor, account_id)
            for eid, etype, data in plan.frames:
                yield _format_sse(eid, etype, data)
                seen.add(eid)
            cursor_seq_local = plan.cursor_seq

            while True:
                if await request.is_disconnected():
                    break
                now = time.monotonic()
                if session_epoch is not None and now >= next_epoch_recheck:
                    try:
                        current_epoch = await asyncio.to_thread(_get_session_epoch)
                    except Exception as exc:
                        log.warning(
                            "closing SSE stream after session epoch check failed (error type=%s)",
                            type(exc).__name__,
                        )
                        break
                    if current_epoch != session_epoch:
                        break
                    next_epoch_recheck = now + SESSION_EPOCH_RECHECK_INTERVAL_S
                timeout = (
                    min(15.0, max(0.0, next_epoch_recheck - time.monotonic()))
                    if session_epoch is not None
                    else 15.0
                )
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    if session_epoch is not None and time.monotonic() >= next_epoch_recheck:
                        continue
                    yield ": keepalive\n\n"
                    continue
                if event is SSE_STREAM_CLOSE:
                    break
                close_after_delivery = (
                    isinstance(event, dict) and event.get("_mail_core_close_after_delivery")
                )
                if account_id and event.get("account_id") and event["account_id"] != str(account_id):
                    if close_after_delivery:
                        break
                    continue
                cursor_id = str(event["id"])
                event_seq = event.get("publication_seq")
                if cursor_id in seen or (event_seq is not None and event_seq <= cursor_seq_local):
                    continue
                yield _format_sse(cursor_id, event["event"], event.get("data") or {})
                seen.add(cursor_id)
                if event_seq is not None:
                    cursor_seq_local = max(cursor_seq_local, int(event_seq))
                if close_after_delivery:
                    break
        finally:
            try:
                if dispatcher is not None and queue is not None:
                    dispatcher.unsubscribe(queue, account_id=str(account_id) if account_id else None)
            finally:
                release_slot()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        background=BackgroundTask(release_slot),
    )
