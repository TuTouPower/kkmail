"""Package G-part-2 unit-mode coverage for outbox retention (R13, design §9.2).

The prune service is exercised against a real SQLAlchemy session on a
SQLite database whose two tables are created with raw DDL matching the
current models (the PostgreSQL JSONB server defaults cannot be created on
SQLite, but every column the retention logic reads or writes is present).
PostgreSQL-backed end-to-end coverage lives in test_outbox_retention.py.

Replay and dispatcher behavior are exercised through the production
functions with their session-factory / publication helpers replaced by
controllable fakes — the same seams the production code uses.
"""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from mail_core.api import sse as sse_mod
from mail_core.mail.storage.models import OutboxEvent, OutboxPublicationState
from mail_core.realtime import outbox as outbox_mod
from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.realtime.outbox import prune_published, pruned_through_seq

ROOT = Path(__file__).resolve().parents[2]
EPOCH = str(uuid.uuid4())
NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=30)
FRESH = NOW - timedelta(hours=1)


# ---------------------------------------------------------------------------
# SQLite-backed retention service
# ---------------------------------------------------------------------------


def _make_session_factory():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE outbox_publication_state (
                    id INTEGER PRIMARY KEY,
                    epoch CHAR(36) NOT NULL,
                    next_seq BIGINT NOT NULL DEFAULT 1,
                    pruned_through_seq BIGINT NOT NULL DEFAULT 0,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type VARCHAR(64) NOT NULL,
                    account_id CHAR(36),
                    payload JSON NOT NULL DEFAULT '{}',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    publication_seq BIGINT,
                    published_at DATETIME
                )
                """
            )
        )
        conn.execute(text("CREATE UNIQUE INDEX ix_outbox_publication_seq ON outbox (publication_seq)"))
    return sessionmaker(bind=engine)


def _seed(Session, rows, *, watermark=0):
    """rows: list of (publication_seq | None, published_at | None)."""
    with Session() as session:
        session.add(
            OutboxPublicationState(
                id=1,
                epoch=uuid.UUID(EPOCH),
                next_seq=max([seq for seq, _ in rows if seq is not None], default=0) + 1,
                pruned_through_seq=watermark,
            )
        )
        ids = {}
        for seq, published_at in rows:
            row = OutboxEvent(
                event_type="sync.progress",
                payload={"seq": seq},
                publication_seq=seq,
                published_at=published_at,
            )
            session.add(row)
            session.flush()
            ids[seq] = row.id
        session.commit()
    return ids


def _remaining_seqs(Session):
    with Session() as session:
        return sorted(
            seq
            for seq in session.scalars(select(OutboxEvent.publication_seq)).all()
            if seq is not None
        )


def _watermark(Session):
    with Session() as session:
        return pruned_through_seq(session)


def test_prune_deletes_old_published_prefix_and_advances_watermark():
    Session = _make_session_factory()
    _seed(Session, [(1, OLD), (2, OLD), (3, OLD)])

    with Session() as session:
        deleted = prune_published(session, now=NOW)
        session.commit()
    assert deleted == 3
    assert _remaining_seqs(Session) == []
    assert _watermark(Session) == 3


def test_prune_delete_and_watermark_advance_share_one_transaction():
    Session = _make_session_factory()
    _seed(Session, [(1, OLD), (2, OLD)])

    with Session() as session:
        assert prune_published(session, now=NOW) == 2
        # Both effects visible together inside the transaction...
        assert pruned_through_seq(session) == 2
        assert list(session.scalars(select(OutboxEvent)).all()) == []
        session.rollback()

    # ...and both are undone together by a rollback: the watermark never
    # claims rows that were not deleted, and vice versa.
    assert _remaining_seqs(Session) == [1, 2]
    assert _watermark(Session) == 0


def test_prune_respects_batch_limit_and_continues_next_call():
    Session = _make_session_factory()
    _seed(Session, [(seq, OLD) for seq in range(1, 7)])

    with Session() as session:
        assert prune_published(session, limit=2, now=NOW) == 2
        session.commit()
    assert _watermark(Session) == 2
    assert _remaining_seqs(Session) == [3, 4, 5, 6]

    with Session() as session:
        assert prune_published(session, limit=2, now=NOW) == 2
        session.commit()
    assert _watermark(Session) == 4
    assert _remaining_seqs(Session) == [5, 6]


def test_prune_batch_is_hard_capped_at_5000_rows():
    Session = _make_session_factory()
    _seed(Session, [(seq, OLD) for seq in range(1, 5002)])

    with Session() as session:
        deleted = prune_published(session, limit=999999, now=NOW)
        session.commit()
    assert deleted == 5000
    assert _watermark(Session) == 5000
    assert _remaining_seqs(Session) == [5001]


def test_prune_never_deletes_unpublished_rows_regardless_of_age():
    Session = _make_session_factory()
    ids = _seed(Session, [(1, OLD), (None, None), (2, OLD)])
    unpublished_id = ids[None]

    with Session() as session:
        assert prune_published(session, now=NOW) == 2
        session.commit()
        survivor = session.get(OutboxEvent, unpublished_id)
        assert survivor is not None
        assert survivor.publication_seq is None
    assert _watermark(Session) == 2


def test_prune_stops_at_newer_row_interleaved_in_sequence():
    Session = _make_session_factory()
    _seed(Session, [(1, OLD), (2, FRESH), (3, OLD)])

    with Session() as session:
        deleted = prune_published(session, now=NOW)
        session.commit()
    # Seq 3 is old, but it sits behind fresh seq 2: deleting it would open
    # a hole in the retained stream, so the prefix stops at seq 1.
    assert deleted == 1
    assert _remaining_seqs(Session) == [2, 3]
    assert _watermark(Session) == 1


def test_prune_keeps_rows_inside_retention_window():
    Session = _make_session_factory()
    _seed(Session, [(1, FRESH), (2, FRESH)])

    with Session() as session:
        assert prune_published(session, now=NOW) == 0
        session.commit()
    assert _remaining_seqs(Session) == [1, 2]
    assert _watermark(Session) == 0


def test_prune_starts_above_existing_watermark():
    Session = _make_session_factory()
    _seed(Session, [(3, OLD), (4, OLD)], watermark=2)

    with Session() as session:
        assert prune_published(session, now=NOW) == 2
        session.commit()
    assert _watermark(Session) == 4


# ---------------------------------------------------------------------------
# SSE replay: retention gap handling (fake DB seams)
# ---------------------------------------------------------------------------


class _FakeDbSession:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _fake_row(seq, *, account_id=None):
    return SimpleNamespace(
        id=1000 + seq,
        publication_seq=seq,
        event_type="sync.progress",
        account_id=account_id,
        payload={"seq": seq},
        created_at=NOW,
    )


def _patch_replay(monkeypatch, *, head, pruned, rows=()):
    monkeypatch.setattr(sse_mod, "get_session_factory", lambda: (lambda: _FakeDbSession()))
    monkeypatch.setattr(sse_mod, "publication_head", lambda session: (EPOCH, head))
    monkeypatch.setattr(sse_mod, "pruned_through_seq", lambda session: pruned)
    monkeypatch.setattr(
        sse_mod,
        "fetch_published_since",
        lambda session, *, after_seq, limit=100, account_id=None: [
            row for row in rows if row.publication_seq > after_seq
        ],
    )


def test_replay_cursor_below_watermark_gets_retention_gap_even_for_small_gap(monkeypatch):
    # Gap to head is only 3 (well below RESYNC_GAP=500), yet rows 8..9 that
    # the client needs are gone: a partial replay must not pretend to be
    # complete.
    _patch_replay(monkeypatch, head=10, pruned=9, rows=[_fake_row(10)])
    plan = sse_mod._build_replay(f"v2:{EPOCH}:7", None)
    assert len(plan.frames) == 1
    cursor_id, event, payload = plan.frames[0]
    assert event == "client.resync_hint"
    assert payload["reason"] == "retention_gap"
    assert payload["pruned_through_seq"] == 9
    assert plan.cursor == f"v2:{EPOCH}:10"
    assert plan.cursor_seq == 10


def test_replay_cursor_below_watermark_with_empty_retention_window(monkeypatch):
    # Everything published has been pruned (pruned == head): same hint.
    _patch_replay(monkeypatch, head=10, pruned=10, rows=[])
    plan = sse_mod._build_replay(f"v2:{EPOCH}:3", None)
    assert [event for _, event, _ in plan.frames] == ["client.resync_hint"]
    assert plan.frames[0][2]["reason"] == "retention_gap"


def test_replay_retention_gap_applies_to_account_filtered_streams(monkeypatch):
    account_id = uuid.uuid4()
    _patch_replay(monkeypatch, head=10, pruned=9, rows=[_fake_row(10, account_id=str(account_id))])
    plan = sse_mod._build_replay(f"v2:{EPOCH}:8", account_id)
    assert [event for _, event, _ in plan.frames] == ["client.resync_hint"]
    assert plan.frames[0][2]["reason"] == "retention_gap"


def test_replay_cursor_at_or_above_watermark_replays_normally(monkeypatch):
    _patch_replay(monkeypatch, head=10, pruned=9, rows=[_fake_row(10)])
    plan = sse_mod._build_replay(f"v2:{EPOCH}:9", None)
    assert [(cursor, event) for cursor, event, _ in plan.frames] == [(f"v2:{EPOCH}:10", "sync.progress")]
    assert plan.cursor_seq == 10

    _patch_replay(monkeypatch, head=10, pruned=4, rows=[_fake_row(6), _fake_row(10)])
    plan = sse_mod._build_replay(f"v2:{EPOCH}:5", None)
    assert [event for _, event, _ in plan.frames] == ["sync.progress", "sync.progress"]
    assert plan.cursor_seq == 10


# ---------------------------------------------------------------------------
# Dispatcher: commit-before-broadcast, retention lag, two instances
# ---------------------------------------------------------------------------


class _FakeDispatchSession:
    def __init__(self, recorder):
        self.recorder = recorder

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def commit(self):
        self.recorder.append("commit")


def _patch_dispatch(monkeypatch, *, head, pruned, rows, batch_count=0, recorder=None):
    recorder = recorder if recorder is not None else []
    monkeypatch.setattr(
        "mail_core.db.session.get_session_factory",
        lambda: (lambda: _FakeDispatchSession(recorder)),
    )

    def fake_publish(session, *, limit=100):
        recorder.append("publish")
        return SimpleNamespace(count=batch_count, first_seq=None, last_seq=None, epoch=uuid.UUID(EPOCH))

    monkeypatch.setattr("mail_core.realtime.publication.publish_committed_batch", fake_publish)
    monkeypatch.setattr(outbox_mod, "publication_head", lambda session: (EPOCH, head))
    monkeypatch.setattr(outbox_mod, "pruned_through_seq", lambda session: pruned)
    monkeypatch.setattr(
        outbox_mod,
        "fetch_published_since",
        lambda session, *, after_seq, limit=100, account_id=None: [
            row for row in rows if row.publication_seq > after_seq
        ],
    )
    return recorder


def _drain(queue):
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_two_dispatcher_instances_both_receive_published_events(monkeypatch):
    rows = [_fake_row(4), _fake_row(5)]
    _patch_dispatch(monkeypatch, head=5, pruned=0, rows=rows)

    async def run():
        dispatchers = [OutboxDispatcher(), OutboxDispatcher()]
        queues = []
        for dispatcher in dispatchers:
            # Both instances are long-running: their baselines were
            # established before these rows were published.
            dispatcher._last_dispatched_seq = 3
            dispatcher._baseline_established = True  # R08: a bare cursor no longer implies an established baseline
            queues.append(dispatcher.subscribe())
        counts = [dispatcher.dispatch_once() for dispatcher in dispatchers]
        received = [_drain(queue) for queue in queues]
        for dispatcher, queue in zip(dispatchers, queues):
            dispatcher.unsubscribe(queue)
        return counts, received

    counts, received = asyncio.run(run())
    assert counts == [2, 2]
    for events in received:
        assert [event["id"] for event in events] == [f"v2:{EPOCH}:4", f"v2:{EPOCH}:5"]


def test_lagging_dispatcher_emits_retention_gap_hint_and_rebuilds_cursor(monkeypatch):
    rows = [_fake_row(12)]
    _patch_dispatch(monkeypatch, head=12, pruned=9, rows=rows)
    dispatcher = OutboxDispatcher()
    dispatcher._last_dispatched_seq = 3
    dispatcher._baseline_established = True  # R08: see above

    async def run():
        queue = dispatcher.subscribe()
        count = dispatcher.dispatch_once()
        events = _drain(queue)
        dispatcher.unsubscribe(queue)
        return count, events

    count, events = asyncio.run(run())
    assert count == 0
    assert dispatcher._last_dispatched_seq == 12
    assert len(events) == 1
    assert events[0]["event"] == "client.resync_hint"
    assert events[0]["data"]["reason"] == "retention_gap"
    assert events[0]["data"]["pruned_through_seq"] == 9


def test_dispatcher_commits_publication_seq_before_broadcast(monkeypatch):
    recorder: list[str] = []
    rows = [_fake_row(4)]
    _patch_dispatch(monkeypatch, head=4, pruned=0, rows=rows, recorder=recorder)
    dispatcher = OutboxDispatcher()
    dispatcher._last_dispatched_seq = 3
    dispatcher._baseline_established = True  # R08: see above

    original_fanout = dispatcher._fanout

    def recording_fanout(event):
        recorder.append("fanout")
        return original_fanout(event)

    dispatcher._fanout = recording_fanout  # type: ignore[method-assign]

    async def run():
        queue = dispatcher.subscribe()
        count = dispatcher.dispatch_once()
        events = _drain(queue)
        dispatcher.unsubscribe(queue)
        return count, events

    count, events = asyncio.run(run())
    assert count == 1
    assert [event["id"] for event in events] == [f"v2:{EPOCH}:4"]
    # Publication happened first, its transaction committed, and only then
    # was anything broadcast to subscribers.
    assert recorder.index("publish") < recorder.index("commit") < recorder.index("fanout")


# ---------------------------------------------------------------------------
# Model / migration alignment (programmatic drift check for unit mode)
# ---------------------------------------------------------------------------


def test_publication_state_model_has_pruned_through_seq_bigint_default_zero():
    column = OutboxPublicationState.__table__.c.pruned_through_seq
    assert column.type.__class__.__name__ == "BigInteger"
    assert column.nullable is False
    assert column.default is not None and column.default.arg == 0
    assert column.server_default is not None and "0" in str(column.server_default.arg)


def test_outbox_model_dropped_dispatched_at_and_old_consumption_index():
    assert "dispatched_at" not in OutboxEvent.__table__.c
    index_names = {index.name for index in OutboxEvent.__table__.indexes}
    assert "ix_outbox_undispatched" not in index_names
    assert "ix_outbox_publication_seq" in index_names
    assert "ix_outbox_unassigned" in index_names
    publication_index = next(i for i in OutboxEvent.__table__.indexes if i.name == "ix_outbox_publication_seq")
    assert publication_index.unique is True


def _load_migration_0026():
    path = ROOT / "src/mail_core/db/alembic/versions/20261026_0026_outbox_retention_watermark.py"
    spec = importlib.util.spec_from_file_location("migration_20261026_0026", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path.read_text(encoding="utf-8")


def test_migration_0026_matches_model_definitions():
    migration, source = _load_migration_0026()
    assert migration.revision == "20261026_0026"
    assert migration.down_revision == "20261026_0025"
    # New column: same name/type/default family as the model declares.
    assert '"pruned_through_seq"' in source or "'pruned_through_seq'" in source or "pruned_through_seq" in source
    assert "BigInteger" in source
    # The old consumption model is removed in the same migration.
    assert "ix_outbox_undispatched" in source
    assert "dispatched_at" in source
    assert "drop_column" in source and "drop_index" in source


def test_alembic_chain_head_is_0026():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(ROOT / "src/mail_core/db/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/mail_core/db/alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["20261026_0026"]
    assert script.get_revision("20261026_0026").down_revision == "20261026_0025"
