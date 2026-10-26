from __future__ import annotations

import os
import time

import pytest

import asyncio
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage import OutboxEvent
from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.realtime.listener import OutboxListenThread
from mail_core.realtime.notify import notify_outbox
from mail_core.realtime.outbox import publication_head

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_listen_thread_dispatches_on_notify_with_subscribers():
    dispatcher = OutboxDispatcher()
    seen: list[str] = []

    # Register a local subscriber so dispatch_once(require_subscribers=True) fans out
    loop = asyncio.new_event_loop()
    q: asyncio.Queue = asyncio.Queue()
    with dispatcher._lock:
        dispatcher._subs["*"].append((loop, q))

    # Capture fanout
    original = dispatcher._fanout

    def _fanout(event):
        # SSE event ids are strings: "v2:{epoch}:{publication_seq}"
        # (design §9.2) — never int-cast them.
        seen.append(str(event["id"]))
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
        row_id = row.id
        notify_outbox(session)
        session.commit()

    deadline = time.time() + 8
    while time.time() < deadline and not seen:
        time.sleep(0.1)

    listener.stop()
    loop.close()
    assert seen, "no event was fanned out"
    # publication_seq is assigned by the publication machinery at
    # dispatch time, so the canonical id is derived after the fact and
    # must match the fanned-out string id exactly.
    with Session() as session:
        epoch, _head = publication_head(session)
        seq = session.scalar(
            select(OutboxEvent.publication_seq).where(OutboxEvent.id == row_id)
        )
    expected_id = f"v2:{epoch}:{seq}"
    assert expected_id in seen, f"expected event {expected_id} in {seen}"


def test_listen_thread_idle_without_subscribers_does_not_dispatch():
    dispatcher = OutboxDispatcher()
    assert not dispatcher.has_local_subscribers()

    seen: list[str] = []
    original = dispatcher._fanout

    def _fanout(event):
        seen.append(str(event["id"]))
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
        notify_outbox(session)
        session.commit()

    time.sleep(0.6)
    listener.stop()
    assert seen == []
