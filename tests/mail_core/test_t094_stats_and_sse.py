"""t094 AC-006 & Finding 3 verification: deferred post-commit stats & SSE/dispatcher safety."""

from __future__ import annotations

import asyncio
import os
import threading
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, select, text

from mail_core.accounts import create_account
from mail_core.api import sse as sse_mod
from mail_core.blobs import archive as archive_mod
from mail_core.db.session import get_session_factory
from mail_core.mail.storage import Folder
from mail_core.providers.base import RemoteFolder, RemoteMessageMeta
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.realtime import outbox as outbox_mod
from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.security.credentials import DictCredentialStore, set_credential_store
from mail_core.sync import engine as engine_mod
from mail_core.sync import retention as retention_mod
from mail_core.sync import sync_account_folders, sync_folder_metadata
from mail_core.sync.retention import (
    MESSAGE_STATS_ANALYZE_COOLDOWN_SECONDS,
    MESSAGE_STATS_BULK_CHANGED_ROWS,
    MESSAGE_STATS_TABLES,
    flush_deferred_message_stats,
    last_message_stats_analyze_at,
    pending_message_stats_rows,
    record_message_stats_rows,
    refresh_message_stats_if_bulk,
    reltuples_within_tolerance,
    reset_message_stats_state,
)

_REQUIRES_PG = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


@pytest.fixture(autouse=True)
def _reset_stats_tracker():
    reset_message_stats_state()
    yield
    reset_message_stats_state()


def _sqlite_session_factory():
    eng = create_engine("sqlite:///:memory:")
    return eng, lambda: retention_mod.Session(eng)


def _pg_reltuples_and_counts(session) -> dict[str, tuple[float, int]]:
    out: dict[str, tuple[float, int]] = {}
    for table in MESSAGE_STATS_TABLES:
        reltuples = float(
            session.scalar(
                text(
                    "SELECT c.reltuples "
                    "FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() AND c.relname = :table"
                ),
                {"table": table},
            )
        )
        count = int(session.scalar(text(f"SELECT COUNT(*) FROM {table}")) or 0)
        out[table] = (reltuples, count)
    return out


def _seed_memory_account(
    monkeypatch,
    *,
    count: int,
    with_mime: bool = False,
    page_size: int = 600,
) -> tuple[uuid.UUID, uuid.UUID, DictCredentialStore]:
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(
        folders=[RemoteFolder("INBOX", "INBOX", "inbox")],
        page_size=page_size,
    )
    metas = [
        RemoteMessageMeta(
            remote_id=f"msg-{i}",
            subject=f"Subject {i}",
            from_address=f"sender{i % 10}@example.test",
            from_name="Sender",
            sort_time=now,
            is_read=False,
            has_attachments=False,
            is_flagged=False,
            uid=i + 1,
            snippet=f"Preview body {i}",
        )
        for i in range(count)
    ]
    mime_payload = (
        b"From: Sender <sender@example.test>\r\n"
        b"Subject: Archived body\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Archived plaintext body content for search and stats.\r\n"
    )
    mime_map = {m.remote_id: mime_payload for m in metas} if with_mime else None
    provider.seed("INBOX", metas, mime_map)

    store = DictCredentialStore({"mem-cred": "secret"})
    set_credential_store(store)
    monkeypatch.setattr(engine_mod, "build_provider", lambda *_a, **_kw: provider)
    monkeypatch.setattr(archive_mod, "build_provider", lambda *_a, **_kw: provider)

    Session = get_session_factory()
    with Session() as session:
        account = create_account(
            session,
            email=f"stats-{uuid.uuid4().hex[:8]}@example.test",
            provider="memory",
            credential_ref="mem-cred",
        )
        session.commit()
        account_id = account.id

    res = sync_account_folders(
        account_id,
        worker_id="w-stats-init",
        store=store,
        execution_origin="foreground",
    )
    assert res["status"] == "ok"
    with Session() as session:
        folder_id = session.scalar(select(Folder.id).where(Folder.account_id == account_id))
        assert folder_id is not None
    return account_id, folder_id, store


# ---------------------------------------------------------------------------
# Fast unit coverage (runs in KKMAIL_TEST_MODE=unit and PG mode)
# ---------------------------------------------------------------------------


def test_unit_stats_accumulation_cooldown_and_deferred_flush(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(retention_mod.time, "monotonic", lambda: clock[0])
    analyze_calls: list[int] = []
    monkeypatch.setattr(
        retention_mod,
        "_run_message_tables_analyze",
        lambda _s: analyze_calls.append(1) or True,
    )

    eng, make_session = _sqlite_session_factory()
    try:
        # Sub-threshold batches do not ANALYZE, but accumulate until >= 1000.
        with make_session() as s:
            assert record_message_stats_rows(s, 400) is False
            s.commit()
        assert analyze_calls == []
        assert pending_message_stats_rows() == 400
        assert last_message_stats_analyze_at() == float("-inf")

        with make_session() as s:
            assert record_message_stats_rows(s, 600) is True
            # Cooldown timestamp MUST NOT advance before commit!
            assert last_message_stats_analyze_at() == float("-inf")
            s.commit()
        assert len(analyze_calls) == 1
        assert pending_message_stats_rows() == 0
        assert last_message_stats_analyze_at() == 1000.0

        # Within 300s cooldown: bulk batch skips ANALYZE and preserves count.
        clock[0] = 1120.0
        with make_session() as s:
            assert record_message_stats_rows(s, 1500) is False
            s.commit()
        assert len(analyze_calls) == 1
        assert pending_message_stats_rows() == 1500

        # Still inside cooldown at +299s: maintenance flush must wait.
        clock[0] = 1299.0
        with make_session() as s:
            assert flush_deferred_message_stats(s) is False
            s.commit()
        assert len(analyze_calls) == 1
        assert pending_message_stats_rows() == 1500

        # Once 300s elapses: maintenance flush ANALYZEs and clears pending on commit.
        clock[0] = 1300.0
        with make_session() as s:
            assert flush_deferred_message_stats(s) is True
            assert last_message_stats_analyze_at() == 1000.0
            assert pending_message_stats_rows() == 1500
            s.commit()
        assert len(analyze_calls) == 2
        assert pending_message_stats_rows() == 0
        assert last_message_stats_analyze_at() == 1300.0
    finally:
        eng.dispose()


def test_unit_stats_rollback_and_nested_savepoint_do_not_consume_cooldown(monkeypatch):
    clock = [2000.0]
    monkeypatch.setattr(retention_mod.time, "monotonic", lambda: clock[0])
    analyze_calls: list[int] = []
    monkeypatch.setattr(
        retention_mod,
        "_run_message_tables_analyze",
        lambda _s: analyze_calls.append(1) or True,
    )

    eng, make_session = _sqlite_session_factory()
    try:
        # Direct rollback must not set cooldown or add pending rows.
        with make_session() as s:
            assert record_message_stats_rows(s, 1200) is True
            s.rollback()
        assert len(analyze_calls) == 1
        assert last_message_stats_analyze_at() == float("-inf")
        assert pending_message_stats_rows() == 0

        # Committed nested savepoint (like events.py NOTIFY) inside rolled-back
        # outer transaction must also NOT consume cooldown.
        with make_session() as s:
            assert record_message_stats_rows(s, 1200) is True
            with s.begin_nested():
                pass
            s.rollback()
        assert len(analyze_calls) == 2
        assert last_message_stats_analyze_at() == float("-inf")
        assert pending_message_stats_rows() == 0

        # Rolled-back nested savepoint inside committed outer transaction discards
        # only the savepoint's bulk stats while committing outer rows.
        with make_session() as s:
            assert record_message_stats_rows(s, 300) is False
            try:
                with s.begin_nested():
                    assert record_message_stats_rows(s, 900) is True
                    raise RuntimeError("abort savepoint")
            except RuntimeError:
                pass
            s.commit()
        assert len(analyze_calls) == 3
        assert last_message_stats_analyze_at() == float("-inf")
        assert pending_message_stats_rows() == 300

        # Next bulk commit on same session is still unblocked immediately.
        clock[0] = 2001.0
        with make_session() as s:
            assert record_message_stats_rows(s, 700) is True
            s.commit()
        assert len(analyze_calls) == 4
        assert last_message_stats_analyze_at() == 2001.0
        assert pending_message_stats_rows() == 0
    finally:
        eng.dispose()


def test_unit_refresh_message_stats_if_bulk_delegates_to_tracker(monkeypatch):
    clock = [3000.0]
    monkeypatch.setattr(retention_mod.time, "monotonic", lambda: clock[0])
    analyze_calls: list[int] = []
    monkeypatch.setattr(
        retention_mod,
        "_run_message_tables_analyze",
        lambda _s: analyze_calls.append(1) or True,
    )

    eng, make_session = _sqlite_session_factory()
    try:
        with make_session() as s:
            assert refresh_message_stats_if_bulk(s, MESSAGE_STATS_BULK_CHANGED_ROWS) is True
            s.commit()
        assert len(analyze_calls) == 1
        assert last_message_stats_analyze_at() == 3000.0
    finally:
        eng.dispose()


def test_unit_stats_thread_safe_accumulation_inside_cooldown(monkeypatch):
    clock = [4000.0]
    monkeypatch.setattr(retention_mod.time, "monotonic", lambda: clock[0])
    analyze_calls: list[int] = []
    monkeypatch.setattr(
        retention_mod,
        "_run_message_tables_analyze",
        lambda _s: analyze_calls.append(1) or True,
    )

    eng, make_session = _sqlite_session_factory()
    try:
        # Enter cooldown with an initial committed bulk batch.
        with make_session() as s:
            assert record_message_stats_rows(s, 1000) is True
            s.commit()
        assert len(analyze_calls) == 1

        clock[0] = 4050.0
        errors: list[BaseException] = []

        def _worker():
            try:
                for _ in range(25):
                    with make_session() as s:
                        assert record_message_stats_rows(s, 60) is False
                        s.commit()
            except BaseException as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        assert not errors
        # 8 threads * 25 commits * 60 rows = 12,000 rows accumulated without loss.
        assert pending_message_stats_rows() == 8 * 25 * 60
        assert len(analyze_calls) == 1

        clock[0] = 4000.0 + MESSAGE_STATS_ANALYZE_COOLDOWN_SECONDS
        with make_session() as s:
            assert flush_deferred_message_stats(s) is True
            s.commit()
        assert len(analyze_calls) == 2
        assert pending_message_stats_rows() == 0
    finally:
        eng.dispose()


def test_unit_sse_and_dispatcher_post_fetch_prune_gap(monkeypatch):
    epoch = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    fake_row_2 = SimpleNamespace(
        id=2,
        publication_seq=2,
        event_type="sync.progress",
        account_id=None,
        payload={"seq": 2},
        created_at=now,
    )

    class _FakeSess:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def commit(self):
            pass

    # SSE replay post-fetch race detection
    sse_pruned = iter([0, 1])
    monkeypatch.setattr(sse_mod, "get_session_factory", lambda: (lambda: _FakeSess()))
    monkeypatch.setattr(sse_mod, "publication_head", lambda _s: (epoch, 2))
    monkeypatch.setattr(sse_mod, "pruned_through_seq", lambda _s: next(sse_pruned, 1))
    monkeypatch.setattr(sse_mod, "fetch_published_since", lambda *_a, **_kw: [fake_row_2])
    plan = sse_mod._build_replay(f"v2:{epoch}:0", None)
    assert [(ev, p["reason"]) for _, ev, p in plan.frames] == [
        ("client.resync_hint", "retention_gap")
    ]
    assert plan.cursor_seq == 2

    # Dispatcher Phase 2 post-fetch race detection
    disp_pruned = iter([0, 1])
    monkeypatch.setattr("mail_core.db.session.get_session_factory", lambda: (lambda: _FakeSess()))
    monkeypatch.setattr(
        "mail_core.realtime.publication.publish_committed_batch",
        lambda _s, *, limit=100: SimpleNamespace(count=0, first_seq=None, last_seq=None, epoch=uuid.UUID(epoch)),
    )
    monkeypatch.setattr(outbox_mod, "publication_head", lambda _s: (epoch, 2))
    monkeypatch.setattr(outbox_mod, "pruned_through_seq", lambda _s: next(disp_pruned, 1))
    monkeypatch.setattr(outbox_mod, "fetch_published_since", lambda *_a, **_kw: [fake_row_2])

    dispatcher = OutboxDispatcher()
    dispatcher._baseline_established = True
    dispatcher._last_dispatched_seq = 0

    async def _run():
        q = dispatcher.subscribe()
        try:
            cnt = dispatcher.dispatch_once()
            evs = []
            while not q.empty():
                evs.append(q.get_nowait())
            return cnt, evs
        finally:
            dispatcher.unsubscribe(q)

    cnt, evs = asyncio.run(_run())
    assert cnt == 0
    assert dispatcher._last_dispatched_seq == 2
    assert len(evs) == 1
    assert evs[0]["event"] == "client.resync_hint"
    assert evs[0]["data"]["reason"] == "retention_gap"


# ---------------------------------------------------------------------------
# Real PostgreSQL integration coverage (AC-006)
# ---------------------------------------------------------------------------


@_REQUIRES_PG
def test_pg_sync_folder_metadata_bulk_refreshes_reltuples_all_three_tables(monkeypatch):
    Session = get_session_factory()
    with Session() as session:
        for table in MESSAGE_STATS_TABLES:
            session.execute(text(f"ANALYZE {table}"))
        session.commit()
        before = _pg_reltuples_and_counts(session)
        assert all(cnt == 0 and rel == 0.0 for rel, cnt in before.values())

    account_id, folder_id, store = _seed_memory_account(monkeypatch, count=1100, page_size=600)
    res = sync_folder_metadata(
        account_id,
        folder_id,
        worker_id="w-bulk-meta",
        store=store,
        execution_origin="foreground",
        max_pages=10,
    )
    assert res["status"] == "ok"
    assert res["upserted"] == 1100
    assert res["exhausted"] is True

    with Session() as session:
        stats = _pg_reltuples_and_counts(session)
    assert stats["messages"][1] == 1100
    assert stats["message_search"][1] == 1100
    assert stats["message_bodies"][1] == 0
    for table, (reltuples, real_count) in stats.items():
        assert reltuples_within_tolerance(reltuples, real_count), (
            f"{table} reltuples={reltuples} out of tolerance for count={real_count}"
        )


@_REQUIRES_PG
def test_pg_run_archive_batch_bulk_refreshes_reltuples_all_three_tables(monkeypatch):
    Session = get_session_factory()
    account_id, folder_id, store = _seed_memory_account(
        monkeypatch, count=1050, with_mime=True, page_size=600
    )
    meta_res = sync_folder_metadata(
        account_id,
        folder_id,
        worker_id="w-arch-meta",
        store=store,
        execution_origin="foreground",
        max_pages=10,
    )
    assert meta_res["upserted"] == 1050

    # Baseline all 3 tables before archiving so message_bodies starts at reltuples=0.
    with Session() as session:
        for table in MESSAGE_STATS_TABLES:
            session.execute(text(f"ANALYZE {table}"))
        session.commit()
        before = _pg_reltuples_and_counts(session)
    assert before["message_bodies"] == (0.0, 0)
    reset_message_stats_state()

    archived_total = 0
    for _ in range(10):
        batch_res = archive_mod.run_archive_batch(
            account_id=account_id,
            worker_id="w-arch-bulk",
            store=store,
            payload={"batch_size": 200},
        )
        assert batch_res["status"] == "ok"
        archived_total += batch_res["completed"]
        if batch_res["claimed"] == 0:
            break
    assert archived_total == 1050

    with Session() as session:
        stats = _pg_reltuples_and_counts(session)
    assert stats["messages"][1] == 1050
    assert stats["message_search"][1] == 1050
    assert stats["message_bodies"][1] == 1050
    assert stats["message_bodies"][0] >= 787.0
    for table, (reltuples, real_count) in stats.items():
        assert reltuples_within_tolerance(reltuples, real_count), (
            f"{table} reltuples={reltuples} out of tolerance for count={real_count}"
        )


@_REQUIRES_PG
def test_pg_short_metadata_and_archive_runs_do_not_trigger_analyze(monkeypatch):
    Session = get_session_factory()
    with Session() as session:
        for table in MESSAGE_STATS_TABLES:
            session.execute(text(f"ANALYZE {table}"))
        session.commit()
    reset_message_stats_state()

    account_id, folder_id, store = _seed_memory_account(
        monkeypatch, count=50, with_mime=True, page_size=100
    )

    analyzed_sql: list[str] = []
    engine = Session.kw["bind"]

    def _capture_sql(_conn, _cursor, statement, _params, _context, _executemany):
        if "ANALYZE " in statement.upper():
            analyzed_sql.append(statement)

    event.listen(engine, "before_cursor_execute", _capture_sql)
    try:
        meta_res = sync_folder_metadata(
            account_id,
            folder_id,
            worker_id="w-short-meta",
            store=store,
            execution_origin="foreground",
            max_pages=5,
        )
        assert meta_res["upserted"] == 50

        arch_res = archive_mod.run_archive_batch(
            account_id=account_id,
            worker_id="w-short-arch",
            store=store,
            payload={"batch_size": 100},
        )
        assert arch_res["completed"] == 50
    finally:
        event.remove(engine, "before_cursor_execute", _capture_sql)

    assert analyzed_sql == []
    assert pending_message_stats_rows() == 100
    with Session() as session:
        stats = _pg_reltuples_and_counts(session)
    assert stats["messages"] == (0.0, 50)
    assert stats["message_bodies"] == (0.0, 50)


@_REQUIRES_PG
def test_pg_cooldown_blocks_repeat_analyze_and_flush_deferred_runs_after_300s(monkeypatch):
    clock = [10_000.0]
    monkeypatch.setattr(retention_mod.time, "monotonic", lambda: clock[0])

    Session = get_session_factory()
    with Session() as session:
        for table in MESSAGE_STATS_TABLES:
            session.execute(text(f"ANALYZE {table}"))
        session.commit()
    reset_message_stats_state()

    analyzed_sql: list[str] = []
    engine = Session.kw["bind"]

    def _capture_sql(_conn, _cursor, statement, _params, _context, _executemany):
        if "ANALYZE " in statement.upper():
            analyzed_sql.append(statement)

    event.listen(engine, "before_cursor_execute", _capture_sql)
    try:
        # First bulk sync triggers one ANALYZE per table (3 statements).
        acc1, fol1, store1 = _seed_memory_account(monkeypatch, count=1000, page_size=1200)
        assert sync_folder_metadata(
            acc1, fol1, worker_id="w-cd-1", store=store1, execution_origin="foreground"
        )["upserted"] == 1000
        assert len(analyzed_sql) == len(MESSAGE_STATS_TABLES)
        assert pending_message_stats_rows() == 0

        # Second bulk sync within 300s cooldown must NOT run ANALYZE, and must retain count.
        clock[0] += 60.0
        acc2, fol2, store2 = _seed_memory_account(monkeypatch, count=1200, page_size=1500)
        assert sync_folder_metadata(
            acc2, fol2, worker_id="w-cd-2", store=store2, execution_origin="foreground"
        )["upserted"] == 1200
        assert len(analyzed_sql) == len(MESSAGE_STATS_TABLES)
        assert pending_message_stats_rows() == 1200

        with Session() as session:
            mid_stats = _pg_reltuples_and_counts(session)
        assert mid_stats["messages"][1] == 2200
        assert mid_stats["messages"][0] == pytest.approx(1000.0, abs=10.0)

        # Maintenance flush before 300s stays blocked.
        clock[0] = 10_000.0 + MESSAGE_STATS_ANALYZE_COOLDOWN_SECONDS - 1.0
        with Session() as session:
            assert flush_deferred_message_stats(session) is False
            session.commit()
        assert len(analyzed_sql) == len(MESSAGE_STATS_TABLES)
        assert pending_message_stats_rows() == 1200

        # Once 300s cooldown elapses, maintenance flush refreshes all 3 tables.
        clock[0] = 10_000.0 + MESSAGE_STATS_ANALYZE_COOLDOWN_SECONDS + 1.0
        with Session() as session:
            assert flush_deferred_message_stats(session) is True
            session.commit()
        assert len(analyzed_sql) == len(MESSAGE_STATS_TABLES) * 2
        assert pending_message_stats_rows() == 0

        with Session() as session:
            after_stats = _pg_reltuples_and_counts(session)
        assert after_stats["messages"][1] == 2200
        assert after_stats["message_search"][1] == 2200
        for table, (reltuples, real_count) in after_stats.items():
            assert reltuples_within_tolerance(reltuples, real_count), (
                f"{table} reltuples={reltuples} out of tolerance for count={real_count}"
            )
    finally:
        event.remove(engine, "before_cursor_execute", _capture_sql)


@_REQUIRES_PG
def test_pg_rollback_does_not_consume_cooldown_or_update_reltuples(monkeypatch):
    clock = [20_000.0]
    monkeypatch.setattr(retention_mod.time, "monotonic", lambda: clock[0])

    Session = get_session_factory()
    with Session() as session:
        for table in MESSAGE_STATS_TABLES:
            session.execute(text(f"ANALYZE {table}"))
        session.commit()
    reset_message_stats_state()

    with Session() as session:
        assert record_message_stats_rows(session, 1000) is True
        # Cooldown must remain unadvanced before commit.
        assert last_message_stats_analyze_at() == float("-inf")
        session.rollback()

    assert last_message_stats_analyze_at() == float("-inf")
    assert pending_message_stats_rows() == 0
    with Session() as session:
        rolled_back_stats = _pg_reltuples_and_counts(session)
    assert all(rel == 0.0 and cnt == 0 for rel, cnt in rolled_back_stats.values())

    # Immediately (+1s) a committed bulk metadata sync must be allowed to ANALYZE.
    clock[0] = 20_001.0
    acc, fol, store = _seed_memory_account(monkeypatch, count=1000, page_size=1200)
    assert sync_folder_metadata(
        acc, fol, worker_id="w-rb-ok", store=store, execution_origin="foreground"
    )["upserted"] == 1000

    assert last_message_stats_analyze_at() == 20_001.0
    with Session() as session:
        stats = _pg_reltuples_and_counts(session)
    assert stats["messages"][1] == 1000
    assert stats["message_search"][1] == 1000
    for table, (reltuples, real_count) in stats.items():
        assert reltuples_within_tolerance(reltuples, real_count), (
            f"{table} reltuples={reltuples} out of tolerance for count={real_count}"
        )


def test_unit_delta_and_worker_sweep_share_retention_stats_tracker(monkeypatch):
    """Cross-module check: delta.py delegates without duplicate timer and worker sweep flushes deferred ANALYZE."""
    from mail_core.sync import delta as delta_mod
    from mail_core.worker import main as worker_mod

    clock = [30_000.0]
    monkeypatch.setattr(retention_mod.time, "monotonic", lambda: clock[0])
    analyze_calls: list[int] = []
    monkeypatch.setattr(
        retention_mod,
        "_run_message_tables_analyze",
        lambda _s: analyze_calls.append(1) or True,
    )

    assert not hasattr(delta_mod, "_last_message_stats_refresh")
    assert not hasattr(delta_mod, "_message_stats_lock")

    eng, make_session = _sqlite_session_factory()
    try:
        # 1. Initial bulk delta consumes 300s cooldown once committed.
        with make_session() as s:
            delta_mod._refresh_message_stats_if_bulk(s, 1000)
            s.commit()
        assert len(analyze_calls) == 1

        # 2. Second burst inside 300s cooldown accumulates deferred rows instead of dropping.
        clock[0] = 30_100.0
        with make_session() as s:
            delta_mod._refresh_message_stats_if_bulk(s, 1200)
            s.commit()
        assert len(analyze_calls) == 1
        assert pending_message_stats_rows() == 1200

        # 3. Periodic worker sweep triggers deferred ANALYZE once 300s cooldown elapses.
        clock[0] = 30_301.0
        monkeypatch.setattr(worker_mod, "schedule_periodic_inbox_sync", lambda *_a, **_kw: 0)
        import mail_core.sync.patrol as patrol_mod
        monkeypatch.setattr(patrol_mod, "schedule_folder_status_patrol", lambda *_a, **_kw: patrol_mod.PatrolResult())
        monkeypatch.setattr(worker_mod, "recheck_unreachable_with_probe", lambda *_a, **_kw: 0)
        import mail_core.db.session as db_session_mod
        monkeypatch.setattr(db_session_mod, "get_session_factory", lambda: make_session)

        worker_mod._schedule_periodic_sync_once()
        assert len(analyze_calls) == 2
        assert pending_message_stats_rows() == 0
    finally:
        eng.dispose()
