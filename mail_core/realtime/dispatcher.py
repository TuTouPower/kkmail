"""In-process outbox dispatcher with subscriber fan-out.

LISTEN/NOTIFY wake is owned by the API process. Workers must only ``pg_notify``
(see ``outbox_dispatch_wake``) — they must not call ``dispatch_once``, or they
would ``mark_dispatched`` with no local SSE subscribers and steal events from
the API process.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

from mail_core.realtime.outbox import fetch_undispatched, mark_dispatched, to_item

log = logging.getLogger("mail_core.realtime.dispatcher")

Subscriber = Callable[[dict[str, Any]], None]


@dataclass
class OutboxDispatcher:
    """Polls undispatched rows and notifies local subscribers only."""

    poll_interval_s: float = 0.5
    _subs: dict[str, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = field(default_factory=lambda: defaultdict(list))
    _lock: threading.Lock = field(default_factory=threading.Lock)
    # Serialises dispatch_once across the LISTEN thread so one batch is never
    # fanned out twice (FOR UPDATE SKIP LOCKED covers other API workers).
    _dispatch_lock: threading.Lock = field(default_factory=threading.Lock)
    _stop: bool = False

    def subscribe(self, *, account_id: str | None = None) -> asyncio.Queue:
        """Register a queue bound to the caller's running event loop."""
        key = account_id or "*"
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subs[key].append((loop, q))
        return q

    def unsubscribe(self, q: asyncio.Queue, *, account_id: str | None = None) -> None:
        key = account_id or "*"
        with self._lock:
            self._subs[key] = [(lp, qq) for (lp, qq) in self._subs.get(key, []) if qq is not q]

    def _isolate(self, q: asyncio.Queue) -> None:
        """Isolate a slow consumer whose queue filled up so it does not block the global outbox."""
        log.warning("isolating slow consumer queue %s", id(q))
        with self._lock:
            for key in list(self._subs.keys()):
                self._subs[key] = [(lp, qq) for (lp, qq) in self._subs[key] if qq is not q]

    def has_local_subscribers(self) -> bool:
        with self._lock:
            return any(bool(v) for v in self._subs.values())

    @staticmethod
    def _put(q: asyncio.Queue, event: dict[str, Any]) -> bool:
        """Enqueue ``event``. On QueueFull, push a resync hint instead and return False."""
        try:
            q.put_nowait(event)
            return True
        except asyncio.QueueFull:
            log.warning("sse queue full; dropping event id=%s", event.get("id"))
            hint = {
                "id": event.get("id"),
                "event": "client.resync_hint",
                "account_id": event.get("account_id"),
                "data": {"reason": "sse_queue_full", "dropped_event_id": event.get("id")},
                "created_at": event.get("created_at"),
            }
            try:
                # Make room for the hint so the client knows to resync.
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                q.put_nowait(hint)
            except asyncio.QueueFull:
                log.warning("sse queue full; could not deliver resync hint id=%s", event.get("id"))
            return False

    def _fanout_one(self, loop: asyncio.AbstractEventLoop, q: asyncio.Queue, event: dict[str, Any]) -> bool:
        """Put on the subscriber loop. Same-thread: call directly (avoid deadlock)."""
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            ok = self._put(q, event)
            if not ok:
                self._isolate(q)
            return ok

        fut: concurrent.futures.Future[bool] = concurrent.futures.Future()

        def _run() -> None:
            try:
                res = self._put(q, event)
                fut.set_result(res)
            except Exception as exc:  # noqa: BLE001
                fut.set_exception(exc)

        try:
            loop.call_soon_threadsafe(_run)
        except RuntimeError:
            self._isolate(q)
            return False  # loop closed; subscriber is going away
        try:
            ok = bool(fut.result(timeout=0.5))
            if not ok:
                self._isolate(q)
            return ok
        except Exception:
            self._isolate(q)
            return False

    def _fanout(self, event: dict[str, Any]) -> bool:
        """Deliver to local subscribers. Returns True if every target accepted the event.

        No subscribers → True (idle drain may mark). Any QueueFull drop → False
        (do **not** mark dispatched; a resync hint was queued for that client).
        """
        account_id = event.get("account_id")
        with self._lock:
            if account_id:
                targets = list(self._subs.get("*", []))
                targets.extend(self._subs.get(str(account_id), []))
            else:
                # Broadcast global events (account_id is None) to all active subscribers
                seen_q_ids = set()
                targets = []
                for sub_list in self._subs.values():
                    for loop, q in sub_list:
                        if id(q) not in seen_q_ids:
                            seen_q_ids.add(id(q))
                            targets.append((loop, q))
        if not targets:
            return True
        ok = True
        for loop, q in targets:
            if not self._fanout_one(loop, q, event):
                ok = False
        return ok

    def dispatch_once(self, *, require_subscribers: bool = False) -> int:
        """Fan out undispatched rows to local subscribers and mark successful ones.

        When ``require_subscribers`` is True and this process has none, skip
        entirely so a worker / idle process cannot steal events from the API.
        Events dropped due to a full SSE queue are left undispatched and the
        slow client receives ``client.resync_hint``.
        """
        if require_subscribers and not self.has_local_subscribers():
            return 0

        from mail_core.db.session import get_session_factory

        Session = get_session_factory()
        with self._dispatch_lock, Session() as session:
            rows = fetch_undispatched(session, limit=100)
            if not rows:
                session.commit()
                return 0
            ids: list[int] = []
            for row in rows:
                item = to_item(row)
                payload = {
                    "id": item.id,
                    "event": item.event_type,
                    "account_id": item.account_id,
                    "data": item.payload,
                    "created_at": item.created_at.isoformat(),
                }
                if self._fanout(payload):
                    ids.append(item.id)
            mark_dispatched(session, ids)
            session.commit()
            return len(ids)

    def request_stop(self) -> None:
        self._stop = True

    def run_forever(self) -> None:
        import time

        self._stop = False
        while not self._stop:
            try:
                self.dispatch_once()
            except Exception:
                log.exception("dispatch tick failed")
            time.sleep(self.poll_interval_s)


_dispatcher: OutboxDispatcher | None = None


def get_dispatcher() -> OutboxDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = OutboxDispatcher()
    return _dispatcher
