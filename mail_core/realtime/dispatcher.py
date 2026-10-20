"""In-process outbox dispatcher with subscriber fan-out.

LISTEN/NOTIFY wake is optional; workers can also run ``outbox_dispatch_wake`` jobs.
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
    """Polls undispatched rows and notifies subscribers."""

    poll_interval_s: float = 0.5
    _subs: dict[str, list[asyncio.Queue]] = field(default_factory=lambda: defaultdict(list))
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stop: bool = False

    def subscribe(self, *, account_id: str | None = None) -> asyncio.Queue:
        key = account_id or "*"
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        with self._lock:
            self._subs[key].append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue, *, account_id: str | None = None) -> None:
        key = account_id or "*"
        with self._lock:
            if q in self._subs.get(key, []):
                self._subs[key].remove(q)

    def _fanout(self, event: dict[str, Any]) -> None:
        account_id = event.get("account_id")
        with self._lock:
            targets = list(self._subs.get("*", []))
            if account_id:
                targets.extend(self._subs.get(str(account_id), []))
        for q in targets:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop when slow consumer — client should resync via Last-Event-ID / hint.
                log.warning("sse queue full; dropping event id=%s", event.get("id"))

    def dispatch_once(self) -> int:
        from mail_core.db.session import get_session_factory

        Session = get_session_factory()
        with Session() as session:
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
