"""In-process outbox dispatcher with subscriber fan-out.

LISTEN/NOTIFY wake is owned by the API process. Workers must only ``pg_notify``
(see ``outbox_dispatch_wake``) — they must not call ``dispatch_once``, or they
would ``mark_dispatched`` with no local SSE subscribers and steal events from
the API process.
"""

from __future__ import annotations

import asyncio
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

    def has_local_subscribers(self) -> bool:
        with self._lock:
            return any(bool(v) for v in self._subs.values())

    @staticmethod
    def _put(q: asyncio.Queue, event: dict[str, Any]) -> None:
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            # Slow consumer — client resyncs via Last-Event-ID / resync hint.
            log.warning("sse queue full; dropping event id=%s", event.get("id"))

    def _fanout(self, event: dict[str, Any]) -> None:
        account_id = event.get("account_id")
        with self._lock:
            targets = list(self._subs.get("*", []))
            if account_id:
                targets.extend(self._subs.get(str(account_id), []))
        for loop, q in targets:
            # asyncio.Queue is not thread-safe: hand off to the queue's own loop.
            try:
                loop.call_soon_threadsafe(self._put, q, event)
            except RuntimeError:
                pass  # loop closed; subscriber is going away

    def dispatch_once(self, *, require_subscribers: bool = False) -> int:
        """Fan out undispatched rows to local subscribers and mark them dispatched.

        When ``require_subscribers`` is True (or when this process has none), skip
        marking so a worker / idle process cannot steal events from the API.
        API LISTEN path uses the default (False) so idle drain still marks rows;
        live clients catch up via Last-Event-ID replay.
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
            ids = []
            for row in rows:
                item = to_item(row)
                payload = {
                    "id": item.id,
                    "event": item.event_type,
                    "account_id": item.account_id,
                    "data": item.payload,
                    "created_at": item.created_at.isoformat(),
                }
                self._fanout(payload)
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
