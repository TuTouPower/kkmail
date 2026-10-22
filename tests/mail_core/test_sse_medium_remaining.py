"""Remaining Medium SSE/outbox/worker hardening (async DB, prune, cursor, globals, cap)."""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.api import sse as sse_mod
from mail_core.api.app import app
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage import OutboxEvent
from mail_core.realtime import events as events_mod
from mail_core.realtime.outbox import fetch_since, prune_dispatched
from tests.mail_core.conftest import TEST_API_KEY

_requires_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _client() -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})


def test_sse_wire_events_match_outbox_enum():
    assert events_mod.SSE_WIRE_EVENTS == {e.value for e in OutboxEventType}
    for name in events_mod.SSE_CORE_CLIENT_EVENTS:
        assert name in events_mod.SSE_WIRE_EVENTS
    for name in events_mod.SSE_ARCHIVE_CLIENT_EVENTS:
        assert name in events_mod.SSE_WIRE_EVENTS


def test_frontend_subscribes_to_core_sse_events():
    """Server/client name contract: core events must appear in MAIL_CORE_EVENTS."""
    path = Path(__file__).resolve().parents[2] / "src" / "frontend" / "src" / "api" / "mailCore.ts"
    if not path.is_file():
        pytest.skip("frontend not present")
    text = path.read_text(encoding="utf-8")
    block = re.search(r"MAIL_CORE_EVENTS\s*=\s*\[(.*?)]\s*as const", text, re.S)
    assert block, "MAIL_CORE_EVENTS list not found"
    listed = set(re.findall(r"['\"]([^'\"]+)['\"]", block.group(1)))
    missing = [e for e in events_mod.SSE_CORE_CLIENT_EVENTS if e not in listed]
    assert not missing, f"frontend missing core SSE events: {missing}"
    # archive.* may be omitted by the UI until archive progress is surfaced (documented drift).


@_requires_db
def test_malformed_last_event_id_emits_resync_hint():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        session.add(OutboxEvent(event_type="sync.progress", payload={}))
        session.commit()

    with _client().stream("GET", "/api/events", headers={"Last-Event-ID": "not-an-int"}) as resp:
        assert resp.status_code == 200
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            if "malformed_last_event_id" in buf:
                break
            if buf.count("event:") >= 3:
                break
        assert "client.resync_hint" in buf
        assert "malformed_last_event_id" in buf


@_requires_db
def test_cursor_ahead_of_head_emits_resync_hint():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        session.add(OutboxEvent(event_type="sync.progress", payload={}))
        session.commit()
        head = session.scalar(select(OutboxEvent.id).order_by(OutboxEvent.id.desc()))

    with _client().stream("GET", "/api/events", headers={"Last-Event-ID": str(head + 1000)}) as resp:
        buf = ""
        for chunk in resp.iter_text():
            buf += chunk
            if "cursor_ahead" in buf:
                break
            if buf.count("event:") >= 3:
                break
        assert "client.resync_hint" in buf
        assert "cursor_ahead" in buf


@_requires_db
def test_account_filtered_replay_includes_global_null_account():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    aid = uuid.uuid4()
    with Session() as session:
        # Ensure account exists for FK when we set account_id — use NULL global + skip FK account row
        # by only inserting NULL-account events and account-scoped via raw UUID without FK? account_id FK
        # allows NULL. For non-null we need an Account row — use only global here vs filter that matches none.
        g = OutboxEvent(event_type="sync.progress", account_id=None, payload={"global": True})
        session.add(g)
        session.commit()
        gid = g.id
        before = gid - 1

    rows = None
    with Session() as session:
        # Filter by a random account id: must still return the global row.
        rows = fetch_since(session, last_event_id=before, limit=50, account_id=aid)
    assert any(r.id == gid and r.account_id is None for r in rows)


@_requires_db
def test_prune_dispatched_removes_old_keeps_undispatched():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        old = OutboxEvent(event_type="sync.progress", payload={"old": True})
        fresh = OutboxEvent(event_type="sync.progress", payload={"fresh": True})
        pending = OutboxEvent(event_type="sync.progress", payload={"pending": True})
        session.add_all([old, fresh, pending])
        session.flush()
        now = datetime.now(timezone.utc)
        old.dispatched_at = now - timedelta(days=30)
        fresh.dispatched_at = now - timedelta(hours=1)
        # pending.dispatched_at stays None
        session.commit()
        old_id, fresh_id, pending_id = old.id, fresh.id, pending.id

    with Session() as session:
        n = prune_dispatched(session, older_than=timedelta(days=7), limit=1000)
        session.commit()
        assert n >= 1
        assert session.get(OutboxEvent, old_id) is None
        assert session.get(OutboxEvent, fresh_id) is not None
        assert session.get(OutboxEvent, pending_id) is not None
        assert session.get(OutboxEvent, pending_id).dispatched_at is None



class _sse_slot_reset:
    def __enter__(self):
        with sse_mod._sse_active_lock:
            self._prev = sse_mod._sse_active
            sse_mod._sse_active = 0
        return self

    def __exit__(self, *a):
        with sse_mod._sse_active_lock:
            sse_mod._sse_active = self._prev


def test_sse_connection_cap_returns_503(monkeypatch):
    monkeypatch.setattr(sse_mod, "MAX_SSE_CONNECTIONS", 0)
    # Force counter path: acquire fails immediately.
    with _sse_slot_reset():
        resp = _client().get("/api/events")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "too many sse connections"

@_requires_db
def test_build_replay_runs_without_event_loop():
    """Regression: replay helper is sync and safe for asyncio.to_thread."""
    plan = sse_mod._build_replay(0, None, malformed=False)
    assert isinstance(plan.frames, list)
    assert plan.cursor >= 0
