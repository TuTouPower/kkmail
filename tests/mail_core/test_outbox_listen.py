from __future__ import annotations

import os
import time

import pytest

import asyncio
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage import OutboxEvent
from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.realtime.listener import OutboxListenThread
from mail_core.realtime.notify import notify_outbox

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_listen_thread_dispatches_on_notify_with_subscribers():
    dispatcher = OutboxDispatcher()
    seen: list[int] = []

    # Register a local subscriber so dispatch_once(require_subscribers=True) fans out
    loop = asyncio.new_event_loop()
    q: asyncio.Queue = asyncio.Queue()
    with dispatcher._lock:
        dispatcher._subs["*"].append((loop, q))

    # Capture fanout
    original = dispatcher._fanout

    def _fanout(event):
        seen.append(int(event["id"]))
        return original(event)

    dispatcher._fanout = _fanout  # type: ignore[method-assign]

    listener = OutboxListenThread(dispatcher, idle_timeout_s=1.0)
    listener.start()
    assert listener.wait_started(5)

    Session = get_session_factory()
    with Session() as session:
        row = OutboxEvent(event_type=OutboxEventType.SYNC_PROGRESS.value, payload={"probe": True})
        session.add(row)
        session.flush()
        event_id = int(row.id)
        notify_outbox(session)
        session.commit()

    deadline = time.time() + 8
    while time.time() < deadline and event_id not in seen:
        time.sleep(0.1)

    listener.stop()
    loop.close()
    assert event_id in seen, f"expected event {event_id} in {seen}"


def test_listen_thread_idle_without_subscribers_does_not_dispatch():
    dispatcher = OutboxDispatcher()
    assert not dispatcher.has_local_subscribers()

    seen: list[int] = []
    original = dispatcher._fanout

    def _fanout(event):
        seen.append(int(event["id"]))
        return original(event)

    dispatcher._fanout = _fanout  # type: ignore[method-assign]

    listener = OutboxListenThread(dispatcher, idle_timeout_s=0.2)
    listener.start()
    assert listener.wait_started(5)

    Session = get_session_factory()
    with Session() as session:
        row = OutboxEvent(event_type=OutboxEventType.SYNC_PROGRESS.value, payload={"probe_no_sub": True})
        session.add(row)
        session.flush()
        event_id = int(row.id)
        notify_outbox(session)
        session.commit()

    time.sleep(0.6)
    listener.stop()
    assert event_id not in seen
