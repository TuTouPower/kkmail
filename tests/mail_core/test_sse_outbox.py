from __future__ import annotations

import os
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.api.app import app
from mail_core.api import sse as sse_mod
from tests.mail_core.conftest import TEST_API_KEY
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage import OutboxEvent
from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.realtime.outbox import fetch_since

_requires_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


@_requires_db
def test_dispatch_marks_outbox_and_sse_replays_last_event_id():
    Session = get_session_factory()
    with Session() as session:
        session.add(
            OutboxEvent(event_type=OutboxEventType.SYNC_PROGRESS.value, payload={"n": 1})
        )
        session.add(
            OutboxEvent(event_type=OutboxEventType.SYNC_COMPLETED.value, payload={"n": 2})
        )
        session.commit()
        ids = session.scalars(select(OutboxEvent.id).order_by(OutboxEvent.id.desc()).limit(2)).all()
        first, second = sorted(ids)

    dispatcher = OutboxDispatcher()

    async def dispatch_with_subscriber():
        queue = dispatcher.subscribe()
        try:
            count = dispatcher.dispatch_once()
            received = [queue.get_nowait()["id"] for _ in range(queue.qsize())]
            assert first in received and second in received
            return count
        finally:
            dispatcher.unsubscribe(queue)

    n = asyncio.run(dispatch_with_subscriber())
    assert n >= 2

    with Session() as session:
        rows = fetch_since(session, last_event_id=first, limit=10)
        types = [r.event_type for r in rows if r.id > first]
        assert OutboxEventType.SYNC_COMPLETED.value in types or any(r.id == second for r in rows)

    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    # StreamingResponse with TestClient: read a bit then stop
    with client.stream("GET", "/api/events", headers={"Last-Event-ID": str(first)}) as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            if "event:" in buf and "data:" in buf:
                break
        assert "id:" in buf
        assert "event:" in buf


@_requires_db
def test_resync_hint_when_gap_huge(monkeypatch):
    monkeypatch.setattr("mail_core.api.sse.RESYNC_GAP", 0)
    Session = get_session_factory()
    with Session() as session:
        # A fresh isolated sequence starts at one. Keep the existing positive
        # replay cursor meaningful without relying on earlier tests' events.
        session.add_all([OutboxEvent(event_type="sync.progress", payload={}) for _ in range(12)])
        session.commit()
        head = session.scalar(select(OutboxEvent.id).order_by(OutboxEvent.id.desc()))
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    with client.stream("GET", "/api/events", headers={"Last-Event-ID": str(max(0, head - 10))}) as resp:
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            if "client.resync_hint" in buf:
                break
        assert "client.resync_hint" in buf


def test_replay_limit_matches_resync_gap():
    assert sse_mod.REPLAY_LIMIT >= sse_mod.RESYNC_GAP


@_requires_db
def test_resync_hint_when_replay_page_full(monkeypatch):
    """If replay returns a full page and head is beyond the page, emit resync_hint."""
    monkeypatch.setattr(sse_mod, "RESYNC_GAP", 50)
    monkeypatch.setattr(sse_mod, "REPLAY_LIMIT", 2)
    Session = get_session_factory()
    with Session() as session:
        for i in range(5):
            session.add(OutboxEvent(event_type="sync.progress", payload={"i": i}))
        session.commit()
        ids = session.scalars(select(OutboxEvent.id).order_by(OutboxEvent.id.desc()).limit(5)).all()
        oldest = min(ids)
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    with client.stream("GET", "/api/events", headers={"Last-Event-ID": str(oldest - 1)}) as resp:
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            if "client.resync_hint" in buf and "replay_truncated" in buf:
                break
            if buf.count("event:") >= 4:
                break
        assert "client.resync_hint" in buf
        assert "replay_truncated" in buf


@_requires_db
def test_dispatch_require_subscribers_skips_mark():
    Session = get_session_factory()
    with Session() as session:
        session.add(OutboxEvent(event_type="sync.progress", payload={"steal": True}))
        session.commit()
        eid = session.scalar(select(OutboxEvent.id).order_by(OutboxEvent.id.desc()))

    dispatcher = OutboxDispatcher()
    assert not dispatcher.has_local_subscribers()
    assert dispatcher.dispatch_once(require_subscribers=True) == 0

    with Session() as session:
        row = session.get(OutboxEvent, eid)
        assert row is not None
        assert row.dispatched_at is None
