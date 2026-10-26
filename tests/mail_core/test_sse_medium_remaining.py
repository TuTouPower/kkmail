"""Remaining Medium SSE/outbox/worker hardening (async DB, prune, cursor, globals, cap)."""

from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse

from mail_core.api import sse as sse_mod
from mail_core.api.app import app
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage import OutboxEvent
from mail_core.realtime.dispatcher import SSE_STREAM_CLOSE
from mail_core.realtime import events as events_mod
from mail_core.realtime.outbox import fetch_since, prune_published
from mail_core.security.auth import AuthPrincipal
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


def test_frontend_invalidates_aggregate_caches_on_account_updates():
    """Account scope changes must refresh organization, lists, and aggregate statistics."""
    path = Path(__file__).resolve().parents[2] / "src" / "frontend" / "src" / "hooks" / "useMailCoreRealtime.ts"
    if not path.is_file():
        pytest.skip("frontend not present")
    text = path.read_text(encoding="utf-8")
    block = re.search(r"MAIL_CORE_INBOX_INVALIDATE_EVENTS\s*=\s*new Set\(\[(.*?)]\)", text, re.S)
    assert block, "MAIL_CORE_INBOX_INVALIDATE_EVENTS set not found"
    listed = set(re.findall(r"['\"]([^'\"]+)['\"]", block.group(1)))
    assert OutboxEventType.ACCOUNT_UPDATED.value in listed


@pytest.mark.parametrize("queue_size", [1, 4])
def test_isolated_sse_stream_ends_after_resync_hint(monkeypatch, queue_size):
    queue = asyncio.Queue(maxsize=queue_size)
    hint = {
        "id": 42,
        "event": "client.resync_hint",
        "account_id": None,
        "data": {"reason": "sse_queue_full"},
    }
    queue.put_nowait(hint)
    if queue_size == 1:
        hint["_mail_core_close_after_delivery"] = True
    else:
        queue.put_nowait(SSE_STREAM_CLOSE)

    class FakeDispatcher:
        def __init__(self):
            self.unsubscribed = []

        def subscribe(self, **_kwargs):
            return queue

        def unsubscribe(self, subscriber, **_kwargs):
            self.unsubscribed.append(subscriber)

    dispatcher = FakeDispatcher()
    monkeypatch.setattr(sse_mod, "get_dispatcher", lambda: dispatcher)
    # _ReplayPlan now requires an explicit cursor_seq (design §11).
    monkeypatch.setattr(
        sse_mod,
        "_build_replay",
        lambda *_args, **_kwargs: sse_mod._ReplayPlan(
            frames=[], cursor=f"v2:{uuid.uuid4()}:0", cursor_seq=0
        ),
    )

    class FakeRequest:
        async def is_disconnected(self):
            return False

    async def run_stream():
        before = sse_mod._sse_active
        response = await sse_mod.stream_events(
            FakeRequest(), last_event_id=None, after=None, account_id=None,
            principal=AuthPrincipal(via="api_key"),
        )
        # Consume the controllable body iterator directly with bounded
        # waits, and always close it so the SSE slot is returned (§11).
        frames = response.body_iterator
        try:
            hint = await asyncio.wait_for(anext(frames), timeout=5)
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(frames), timeout=5)
        finally:
            await frames.aclose()
        assert sse_mod._sse_active == before
        assert dispatcher.unsubscribed == [queue]
        return hint

    hint_frame = asyncio.run(run_stream())
    assert "event: client.resync_hint" in hint_frame


@pytest.mark.parametrize(
    "last_event_id,after",
    [("not-an-int", None), ("-1", None), (None, -1)],
)
def test_malformed_or_negative_replay_cursors_emit_resync_hint(monkeypatch, last_event_id, after):
    # Whole-test replacement (design §9.2 / §11): the pre-v2 protocol
    # passed integer cursors plus a `malformed` flag to _build_replay and
    # emitted reason="malformed_last_event_id". The current protocol
    # passes the raw cursor string through to _build_replay(raw_cursor,
    # account_id) and answers any unparseable / non-v2 cursor with a
    # resync hint whose reason is "epoch_mismatch". The behavioural
    # contract — a malformed or negative cursor yields exactly one
    # resync hint and the stream then ends — is unchanged.
    captured = {}
    queue = asyncio.Queue(maxsize=2)
    queue.put_nowait(SSE_STREAM_CLOSE)
    head_cursor = f"v2:{uuid.uuid4()}:0"

    class FakeDispatcher:
        def subscribe(self, **_kwargs):
            return queue

        def unsubscribe(self, *_args, **_kwargs):
            return None

    class FakeRequest:
        async def is_disconnected(self):
            return False

    def build_replay(cursor, account_id):
        captured.update(cursor=cursor, account_id=account_id)
        return sse_mod._ReplayPlan(
            frames=[(head_cursor, "client.resync_hint", {"reason": "epoch_mismatch"})],
            cursor=head_cursor,
            cursor_seq=0,
        )

    monkeypatch.setattr(sse_mod, "get_dispatcher", lambda: FakeDispatcher())
    monkeypatch.setattr(sse_mod, "_build_replay", build_replay)
    with _sse_slot_reset():
        async def drain_stream():
            response = await sse_mod.stream_events(
                FakeRequest(), last_event_id=last_event_id, after=after, account_id=None,
                principal=AuthPrincipal(via="api_key"),
            )
            # Bounded, explicitly closed consumption of the body
            # iterator (§11); the slot must be returned afterwards.
            frames_iter = response.body_iterator
            frames = []
            try:
                while True:
                    try:
                        frames.append(await asyncio.wait_for(anext(frames_iter), timeout=5))
                    except StopAsyncIteration:
                        break
            finally:
                await frames_iter.aclose()
            return frames

        frames = asyncio.run(drain_stream())
        assert sse_mod._sse_active == 0

    assert captured == {"cursor": last_event_id or after, "account_id": None}
    assert len(frames) == 1
    assert "client.resync_hint" in frames[0]
    assert "epoch_mismatch" in frames[0]


@_requires_db
def test_malformed_last_event_id_emits_resync_hint():
    # Current v2 protocol semantics (design §9.2): a Last-Event-ID that is
    # not a v2:epoch:seq cursor is answered with reason="epoch_mismatch"
    # (the pre-v2 "malformed_last_event_id" reason no longer exists).
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
            if "epoch_mismatch" in buf:
                break
            if buf.count("event:") >= 3:
                break
        assert "client.resync_hint" in buf
        assert "epoch_mismatch" in buf


@_requires_db
def test_cursor_ahead_of_head_emits_resync_hint():
    # Replay cursors are v2:epoch:seq over publication_seq (design §9.2);
    # a v2 cursor ahead of the publication head emits cursor_ahead.
    from mail_core.db.session import get_session_factory
    from mail_core.realtime.outbox import publication_head

    Session = get_session_factory()
    with Session() as session:
        session.add(OutboxEvent(event_type="sync.progress", payload={}))
        session.commit()
        epoch, head_seq = publication_head(session)
        # publication_head lazily creates the publication-state (epoch)
        # row inside this session; commit it for real. Without this the
        # row is rolled back when the block exits, the server then mints
        # a different epoch, and the cursor below is answered with
        # epoch_mismatch instead of cursor_ahead.
        session.commit()

    ahead_cursor = f"v2:{epoch}:{head_seq + 1000}"
    with _client().stream("GET", "/api/events", headers={"Last-Event-ID": ahead_cursor}) as resp:
        assert resp.status_code == 200
        buf = ""
        # Bounded read: stop at the hint, at a hard deadline, or after a
        # capped number of chunks — the previous loop could block on
        # iter_text() forever when the hint never arrived.
        deadline = time.monotonic() + 10
        for chunk in resp.iter_text():
            buf += chunk
            if "cursor_ahead" in buf:
                break
            if time.monotonic() > deadline or buf.count("event:") >= 50:
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
def test_prune_published_removes_old_keeps_unpublished():
    # Whole-test replacement (design §9.2): retention no longer keys on
    # the removed dispatched_at column / prune_dispatched name. The
    # current prune_published deletes the expired continuous prefix of
    # rows ordered by publication_seq (by published_at), never deletes
    # unpublished rows, and advances pruned_through_seq with the prefix.
    from mail_core.db.session import get_session_factory
    from mail_core.realtime.outbox import pruned_through_seq
    from mail_core.realtime.publication import get_publication_state

    Session = get_session_factory()
    with Session() as session:
        state = get_publication_state(session)
        base_seq = int(state.next_seq)
        now = datetime.now(timezone.utc)
        old = OutboxEvent(
            event_type="sync.progress", payload={"old": True},
            publication_seq=base_seq, published_at=now - timedelta(days=30),
        )
        fresh = OutboxEvent(
            event_type="sync.progress", payload={"fresh": True},
            publication_seq=base_seq + 1, published_at=now - timedelta(hours=1),
        )
        pending = OutboxEvent(event_type="sync.progress", payload={"pending": True})
        session.add_all([old, fresh, pending])
        state.next_seq = base_seq + 2
        session.commit()
        old_id, fresh_id, pending_id = old.id, fresh.id, pending.id

    with Session() as session:
        n = prune_published(session, older_than=timedelta(days=7), limit=1000)
        session.commit()
        # Only the old row is an expired prefix: the fresh row behind it
        # blocks any later deletion, and the unpublished row is immune.
        assert n == 1
        assert session.get(OutboxEvent, old_id) is None
        assert session.get(OutboxEvent, fresh_id) is not None
        assert session.get(OutboxEvent, pending_id) is not None
        assert session.get(OutboxEvent, pending_id).publication_seq is None
        assert pruned_through_seq(session) == base_seq



class _sse_slot_reset:
    def __enter__(self):
        with sse_mod._sse_active_lock:
            self._prev = sse_mod._sse_active
            sse_mod._sse_active = 0
        return self

    def __exit__(self, *a):
        with sse_mod._sse_active_lock:
            sse_mod._sse_active = self._prev


def test_sse_connection_cap_invalid_env_falls_back_and_warns(monkeypatch, caplog):
    monkeypatch.delenv("MAIL_CORE_SSE_MAX_CONNECTIONS", raising=False)
    monkeypatch.setenv("MAIL_CORE_SSE_MAX_CONNECTIONS", "not-a-number")
    monkeypatch.setattr(sse_mod, "_sse_max_connections_cache", None)

    with caplog.at_level("WARNING", logger="mail_core.api.sse"):
        assert sse_mod._max_sse_connections() == 128
        assert sse_mod._max_sse_connections() == 128

    assert caplog.text.count("invalid MAIL_CORE_SSE_MAX_CONNECTIONS") == 1
    assert "not-a-number" in caplog.text


def test_sse_connection_cap_returns_503(monkeypatch):
    monkeypatch.setattr(sse_mod, "_sse_max_connections_cache", 0)
    # Force counter path: acquire fails immediately.
    with _sse_slot_reset():
        resp = _client().get("/api/events")
        assert resp.status_code == 503
        assert resp.json()["detail"] == "too many sse connections"


def test_sse_slot_is_reserved_before_stream_response_is_created(monkeypatch):
    monkeypatch.setattr(sse_mod, "_sse_max_connections_cache", 1)
    scope = {"type": "http", "method": "GET", "path": "/api/events", "headers": [], "query_string": b""}
    with _sse_slot_reset():
        first = asyncio.run(
            sse_mod.stream_events(
                Request(scope), last_event_id=None, after=None, account_id=None,
                principal=AuthPrincipal(via="api_key"),
            )
        )
        assert isinstance(first, StreamingResponse)
        assert sse_mod._sse_active == 1

        second = asyncio.run(
            sse_mod.stream_events(
                Request(scope), last_event_id=None, after=None, account_id=None,
                principal=AuthPrincipal(via="api_key"),
            )
        )
        assert isinstance(second, JSONResponse)
        assert second.status_code == 503
        assert sse_mod._sse_active == 1

        assert first.background is not None
        asyncio.run(first.background())
        assert sse_mod._sse_active == 0

@_requires_db
def test_build_replay_runs_without_event_loop():
    """Regression: replay helper is sync and safe for asyncio.to_thread.

    Adapted to the v2 protocol: _build_replay takes the raw cursor
    (str | None) — the integer cursor and the removed `malformed` kwarg
    are gone — and returns a plan whose cursor is a v2:epoch:seq string
    with an explicit cursor_seq.
    """
    plan = sse_mod._build_replay(None, None)
    assert isinstance(plan.frames, list)
    assert plan.cursor.startswith("v2:")
    assert plan.cursor_seq >= 0
