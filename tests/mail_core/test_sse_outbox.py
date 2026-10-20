from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage import OutboxEvent
from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.realtime.outbox import fetch_since, mark_dispatched

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


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
    n = dispatcher.dispatch_once()
    assert n >= 2

    with Session() as session:
        rows = fetch_since(session, last_event_id=first, limit=10)
        types = [r.event_type for r in rows if r.id > first]
        assert OutboxEventType.SYNC_COMPLETED.value in types or any(r.id == second for r in rows)

    client = TestClient(app)
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


def test_resync_hint_when_gap_huge(monkeypatch):
    monkeypatch.setattr("mail_core.api.sse.RESYNC_GAP", 0)
    Session = get_session_factory()
    with Session() as session:
        session.add(OutboxEvent(event_type="sync.progress", payload={}))
        session.commit()
        head = session.scalar(select(OutboxEvent.id).order_by(OutboxEvent.id.desc()))
    client = TestClient(app)
    with client.stream("GET", "/api/events", headers={"Last-Event-ID": str(max(0, head - 10))}) as resp:
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            if "client.resync_hint" in buf:
                break
        assert "client.resync_hint" in buf
