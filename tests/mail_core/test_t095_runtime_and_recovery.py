"""t095 runtime probe, pool contention (AC-002), and SIGKILL crash recovery (AC-006) tests."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import threading
import time
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, TimeoutError as SATimeoutError

from mail_core import liveness, runtime_budget
from mail_core.api.app import app
from mail_core.db import session as db_session
from mail_core.liveness import write_liveness_stamp
from mail_core.mail.storage.models import (
    Account,
    AppSetting,
    Folder,
    Message,
    MessageLocation,
    OutboxEvent,
    SyncCheckpoint,
)
from mail_core.readiness import ReadinessProbe, get_readiness_probe, read_worker_active_via_core
from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.realtime.listener import OutboxListenThread, _dsn_from_settings
from mail_core.worker.heartbeat import HEARTBEAT_PREFIX, record_heartbeat


@pytest.fixture(autouse=True)
def _reset_readiness_probe_singleton():
    get_readiness_probe().invalidate()
    yield
    get_readiness_probe().invalidate()


def _fake_engine_with_fresh_heartbeat():
    now_iso = datetime.now(timezone.utc).isoformat()
    payload = f'{{"worker_id": "w1", "updated_at": "{now_iso}", "active_jobs": 0}}'

    class _Scalars:
        def all(self):
            return [payload]

    class _Result:
        def scalars(self):
            return _Scalars()

    class _Conn:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def execution_options(self, **_kwargs):
            return self

        def execute(self, *_args, **_kwargs):
            return _Result()

    class _Engine:
        def connect(self):
            return _Conn()

    return _Engine()


def test_ac002_runtime_budget_arithmetic():
    """AC-002: single runtime budget defines exact data-plane + control-plane ceilings."""
    assert runtime_budget.DEFAULT_DB_POOL_SIZE == 4
    assert runtime_budget.DEFAULT_DB_MAX_OVERFLOW == 4
    assert runtime_budget.DEFAULT_LISTEN_CONNECTIONS == 2
    assert runtime_budget.DEFAULT_MAINTENANCE_HEADROOM == 6
    assert runtime_budget.MAX_CLIENT_CONNECTIONS == (
        runtime_budget.DEFAULT_DB_POOL_SIZE
        + runtime_budget.DEFAULT_DB_MAX_OVERFLOW
        + runtime_budget.DEFAULT_LISTEN_CONNECTIONS
        + runtime_budget.DEFAULT_MAINTENANCE_HEADROOM
    ) == 16
    assert runtime_budget.DEFAULT_TOTAL_SLOTS == 8
    assert runtime_budget.MAX_TOTAL_PG_CONNECTIONS == 24
    assert runtime_budget.COMPOSE_PG_MAX_CONNECTIONS == 40
    assert runtime_budget.MAX_TOTAL_PG_CONNECTIONS < runtime_budget.COMPOSE_PG_MAX_CONNECTIONS


def test_finding7_embedded_rejects_missing_corrupt_stale_stamp_preserves_distributed(
    monkeypatch, tmp_path
):
    """Finding 7 + t096 AC-005: local stamp must exist and be valid JSON dict when checked."""
    stamp_file = tmp_path / "embedded-liveness.json"
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "1")
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(stamp_file))

    engine = _fake_engine_with_fresh_heartbeat()

    # 1. Missing stamp in embedded mode must report inactive even with fresh DB heartbeat.
    active, _ = read_worker_active_via_core(engine)
    assert active is False

    # 2. Corrupt JSON stamp must report inactive.
    stamp_file.write_text("{corrupt-json", encoding="utf-8")
    active, _ = read_worker_active_via_core(engine)
    assert active is False

    # 3. Valid JSON that is not a dict (e.g., list / null) must report inactive.
    for raw in ("[1, 2, 3]", "null", "123"):
        stamp_file.write_text(raw, encoding="utf-8")
        active, _ = read_worker_active_via_core(engine)
        assert active is False

    # 4. Unreadable stamp (read_liveness_stamp returns None) must report inactive.
    write_liveness_stamp(stamp_file, progress=1, worker_id="w1")
    with monkeypatch.context() as mp:
        mp.setattr("mail_core.readiness.read_liveness_stamp", lambda: None)
        active, _ = read_worker_active_via_core(engine)
        assert active is False

    # 5. Stale stamp must report inactive.
    write_liveness_stamp(stamp_file, progress=1, worker_id="w1")
    stale_at = time.time() - 3600.0
    os.utime(stamp_file, (stale_at, stale_at))
    active, _ = read_worker_active_via_core(engine)
    assert active is False

    # 6. Fresh valid stamp reports active.
    write_liveness_stamp(stamp_file, progress=2, worker_id="w1")
    active, lag = read_worker_active_via_core(engine)
    assert active is True
    assert lag is not None

    # 7. Explicit MAIL_CORE_LIVENESS_STAMP still checks local stamp even when embedded=0.
    missing_explicit = tmp_path / "missing-explicit.json"
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "0")
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(missing_explicit))
    active, _ = read_worker_active_via_core(engine)
    assert active is False

    # 8. Distributed mode (embedded=0 and no explicit stamp env) preserves t096 AC-005.
    monkeypatch.delenv("MAIL_CORE_LIVENESS_STAMP", raising=False)
    monkeypatch.delenv("MAIL_CORE_DATA_DIR", raising=False)
    monkeypatch.setattr(liveness, "DEFAULT_STAMP_PATH", str(tmp_path / "absent-default.json"))
    active, lag = read_worker_active_via_core(engine)
    assert active is True
    assert lag is not None


def test_finding7_ready_invalidates_probe_on_all_failures_and_listener_error(
    monkeypatch, tmp_path
):
    """Finding 7: DB error, schema mismatch, LISTEN down/disconnect, worker error all invalidate cache."""
    probe = ReadinessProbe(ttl_s=60.0)
    monkeypatch.setattr("mail_core.readiness._probe", probe)
    monkeypatch.setenv("MAIL_CORE_REQUIRE_WORKER_READY", "1")
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "1")

    stamp_file = tmp_path / "unit-liveness.json"
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(stamp_file))
    write_liveness_stamp(stamp_file, progress=1, worker_id="w1")

    class _Listener:
        def __init__(self, ready_flag: bool) -> None:
            self.listen_ready = ready_flag

    listener = _Listener(True)
    monkeypatch.setattr("mail_core.api.app._code_schema_head", lambda: "head-rev")
    monkeypatch.setattr("mail_core.mail.storage.health.get_current_schema_revision", lambda: "head-rev")
    monkeypatch.setattr("mail_core.realtime.listener.get_outbox_listener", lambda: listener)
    monkeypatch.setattr("mail_core.db.session.get_engine", lambda *a, **k: _fake_engine_with_fresh_heartbeat())

    client = TestClient(app)

    def _warm_cache() -> None:
        write_liveness_stamp(stamp_file, progress=1, worker_id="w1")
        res = client.get("/ready")
        assert res.status_code == 200
        assert probe.cached_worker_active() is True

    # 1. DB outage invalidates cache so recovery sees missing stamp immediately.
    _warm_cache()
    stamp_file.unlink()
    monkeypatch.setattr(
        "mail_core.mail.storage.health.get_current_schema_revision",
        lambda: (_ for _ in ()).throw(OperationalError("SELECT 1", {}, Exception("down"))),
    )
    res_db = client.get("/ready")
    assert res_db.status_code == 503
    assert res_db.json()["reason"] == "database: OperationalError"
    assert probe.cached_worker_active() is None

    monkeypatch.setattr("mail_core.mail.storage.health.get_current_schema_revision", lambda: "head-rev")
    res_after_db = client.get("/ready")
    assert res_after_db.status_code == 503
    assert res_after_db.json()["reason"] == "worker_not_running"

    # 2. Schema mismatch invalidates cache.
    _warm_cache()
    stamp_file.unlink()
    monkeypatch.setattr("mail_core.mail.storage.health.get_current_schema_revision", lambda: "old-rev")
    res_schema = client.get("/ready")
    assert res_schema.status_code == 503
    assert res_schema.json()["reason"] == "schema_out_of_date"
    assert probe.cached_worker_active() is None

    monkeypatch.setattr("mail_core.mail.storage.health.get_current_schema_revision", lambda: "head-rev")
    res_after_schema = client.get("/ready")
    assert res_after_schema.status_code == 503
    assert res_after_schema.json()["reason"] == "worker_not_running"

    # 3. LISTEN not ready invalidates cache.
    _warm_cache()
    stamp_file.unlink()
    listener.listen_ready = False
    res_listen = client.get("/ready")
    assert res_listen.status_code == 503
    assert res_listen.json()["reason"] == "outbox_listener"
    assert probe.cached_worker_active() is None

    listener.listen_ready = True
    res_after_listen = client.get("/ready")
    assert res_after_listen.status_code == 503
    assert res_after_listen.json()["reason"] == "worker_not_running"

    # 4. Worker check exception and worker_not_running 503 both invalidate cache.
    _warm_cache()
    invalidate_calls = 0
    orig_invalidate = probe.invalidate

    def _spy_invalidate() -> None:
        nonlocal invalidate_calls
        invalidate_calls += 1
        orig_invalidate()

    with monkeypatch.context() as mp:
        mp.setattr(probe, "invalidate", _spy_invalidate)
        probe._cached_at = 0.0  # simulate TTL expiry while old snapshot still exists
        mp.setattr(
            "mail_core.readiness.read_worker_active_via_core",
            lambda *_a, **_k: (_ for _ in ()).throw(OperationalError("SELECT", {}, Exception("worker query boom"))),
        )
        res_worker_exc = client.get("/ready")
        assert res_worker_exc.status_code == 503
        assert res_worker_exc.json()["reason"] == "worker_not_running"
        assert invalidate_calls >= 1
        assert probe.cached_worker_active() is None

    probe.snapshot(schema_revision="head-rev", listener_ready=True, worker_active=False)
    res_worker_false = client.get("/ready")
    assert res_worker_false.status_code == 503
    assert probe.cached_worker_active() is None

    # 5. OutboxListenThread loop error immediately invalidates ReadinessProbe.
    probe.snapshot(schema_revision="head-rev", listener_ready=True, worker_active=True)
    assert probe.cached_worker_active() is True

    disconnected = threading.Event()

    class _FakeConn:
        def execute(self, _sql):
            return None

        def notifies(self, **_kwargs):
            disconnected.set()
            raise OperationalError("LISTEN lost", {}, Exception("eof"))

        def close(self):
            return None

    import psycopg

    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: _FakeConn())
    real_listener = OutboxListenThread(
        OutboxDispatcher(),
        dsn="postgresql://unused",
        reconnect_s=0.2,
    )
    real_listener.start()
    try:
        assert disconnected.wait(timeout=3.0)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and probe.cached_worker_active() is not None:
            time.sleep(0.01)
        assert probe.cached_worker_active() is None
    finally:
        real_listener.stop(timeout=2.0)


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_ac002_pg_pool_contention_and_explicit_timeout(monkeypatch):
    """AC-002: 4+4 pool serves concurrent API+heartbeat+worker work and fails deterministically >8."""
    for var in (
        "MAIL_CORE_DB_POOL_SIZE",
        "MAIL_CORE_DB_MAX_OVERFLOW",
        "MAIL_CORE_DB_POOL_TIMEOUT",
    ):
        monkeypatch.delenv(var, raising=False)

    if db_session._engine is not None:
        db_session._engine.dispose()
        db_session._engine = None
        db_session._SessionLocal = None

    monkeypatch.setenv("MAIL_CORE_DB_POOL_TIMEOUT", "5.0")
    Session = db_session.get_session_factory()
    engine = db_session.get_engine()
    assert engine.pool.size() == runtime_budget.DEFAULT_DB_POOL_SIZE == 4
    assert engine.pool._max_overflow == runtime_budget.DEFAULT_DB_MAX_OVERFLOW == 4

    acc_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(
                id=acc_id,
                email=f"pool-ac002-{acc_id.hex[:6]}@example.com",
                provider="stub",
                sync_enabled=True,
            )
        )
        session.flush()
        session.add(
            Folder(
                id=folder_id,
                account_id=acc_id,
                remote_id="INBOX",
                name="INBOX",
                role="inbox",
            )
        )
        session.flush()
        session.add(
            SyncCheckpoint(
                account_id=acc_id,
                folder_id=folder_id,
                cursor={"uid": 1},
                full_scan_complete=True,
            )
        )
        session.commit()

    def _run_mixed_client(idx: int) -> float:
        started = time.monotonic()
        role = idx % 3
        for step in range(3):
            if role == 0:
                # Simulated API short read.
                with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                    count = conn.execute(text("SELECT count(*) FROM accounts")).scalar_one()
                    assert int(count) >= 1
            elif role == 1:
                # Simulated heartbeat tx.
                with Session() as s:
                    record_heartbeat(s, f"pool-worker-{idx}", active_jobs=step)
                    s.commit()
            else:
                # Simulated worker checkpoint read + short tx.
                with Session() as s:
                    cp = s.get(SyncCheckpoint, {"account_id": acc_id, "folder_id": folder_id})
                    assert cp is not None
                    s.execute(text("SELECT pg_sleep(0.01)"))
                    s.commit()
        return time.monotonic() - started

    started_all = time.monotonic()
    with ThreadPoolExecutor(max_workers=12) as pool:
        durations = list(pool.map(_run_mixed_client, range(12)))
    elapsed_all = time.monotonic() - started_all
    assert len(durations) == 12
    assert elapsed_all < 10.0
    assert engine.pool.checkedout() == 0

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        idle_in_tx = conn.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND state = 'idle in transaction'"
            )
        ).scalar_one()
        assert int(idle_in_tx) == 0

    # Phase 2: saturating 4+4=8 connections must fail deterministically with SATimeoutError.
    engine.dispose()
    db_session._engine = None
    db_session._SessionLocal = None
    monkeypatch.setenv("MAIL_CORE_DB_POOL_TIMEOUT", "0.35")
    bounded_engine = db_session.get_engine()

    held = []
    try:
        for _ in range(
            runtime_budget.DEFAULT_DB_POOL_SIZE + runtime_budget.DEFAULT_DB_MAX_OVERFLOW
        ):
            conn = bounded_engine.connect()
            conn.execute(text("SELECT 1"))
            held.append(conn)
        assert bounded_engine.pool.checkedout() == 8

        t0 = time.monotonic()
        with pytest.raises(SATimeoutError):
            bounded_engine.connect()
        timeout_elapsed = time.monotonic() - t0
        assert 0.2 <= timeout_elapsed < 2.5

        # Releasing one connection unblocks subsequent checkout immediately.
        held.pop().close()
        with bounded_engine.connect() as recovered_conn:
            assert recovered_conn.execute(text("SELECT 1")).scalar_one() == 1
    finally:
        for conn in held:
            try:
                conn.close()
            except Exception:
                pass
        bounded_engine.dispose()
        db_session._engine = None
        db_session._SessionLocal = None


@contextmanager
def _track_ready_sql_and_wire_rollbacks(monkeypatch):
    """Capture SQL statements, non-IDLE rollbacks, and psycopg wire commands."""
    import psycopg

    executed_sql: list[str] = []
    non_idle_rollbacks: list[int] = []
    wire_commands: list[bytes] = []

    def _on_before_cursor(_conn, _cursor, statement, _parameters, _context, _executemany):
        executed_sql.append(statement)

    def _on_rollback(conn):
        driver_conn = getattr(getattr(conn, "connection", None), "driver_connection", None)
        if driver_conn is not None and driver_conn.pgconn.transaction_status != psycopg.pq.TransactionStatus.IDLE:
            non_idle_rollbacks.append(int(driver_conn.pgconn.transaction_status))

    orig_exec_command = psycopg.Connection._exec_command

    def _spy_exec_command(self, command, *args, **kwargs):
        cmd_bytes = command.encode() if isinstance(command, str) else bytes(command)
        wire_commands.append(cmd_bytes)
        return orig_exec_command(self, command, *args, **kwargs)

    event.listen(Engine, "before_cursor_execute", _on_before_cursor)
    event.listen(Engine, "rollback", _on_rollback)
    monkeypatch.setattr(psycopg.Connection, "_exec_command", _spy_exec_command)
    try:
        yield executed_sql, non_idle_rollbacks, wire_commands
    finally:
        event.remove(Engine, "before_cursor_execute", _on_before_cursor)
        event.remove(Engine, "rollback", _on_rollback)


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_finding7_pg_ready_fault_injection_and_zero_rollback(monkeypatch, tmp_path):
    """Finding 7 + AC-005 against real PG: stamp checks, cache invalidation, LISTEN kill, zero ROLLBACK."""
    Session = db_session.get_session_factory()
    with Session() as session:
        record_heartbeat(session, "pg-ready-worker", active_jobs=0)
        session.commit()

    app_name = f"kkmail_ready_listen_{uuid.uuid4().hex[:10]}"
    base_dsn = _dsn_from_settings()
    separator = "&" if "?" in base_dsn else "?"
    tagged_dsn = f"{base_dsn}{separator}application_name={app_name}"

    listener = OutboxListenThread(
        OutboxDispatcher(),
        dsn=tagged_dsn,
        reconnect_s=1.5,
        idle_timeout_s=0.2,
    )
    listener.start()
    assert listener.wait_started(5.0)
    monkeypatch.setattr("mail_core.realtime.listener.get_outbox_listener", lambda: listener)

    probe = ReadinessProbe(ttl_s=30.0)
    monkeypatch.setattr("mail_core.readiness._probe", probe)

    stamp_file = tmp_path / "pg-embedded-liveness.json"
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "1")
    monkeypatch.setenv("MAIL_CORE_REQUIRE_WORKER_READY", "1")
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(stamp_file))

    client = TestClient(app)
    try:
        with _track_ready_sql_and_wire_rollbacks(monkeypatch) as (
            executed_sql,
            non_idle_rollbacks,
            wire_commands,
        ):
            # 1. Embedded mode: missing / corrupt / stale stamp -> 503 even with fresh PG heartbeat.
            res_missing = client.get("/ready")
            assert res_missing.status_code == 503
            assert res_missing.json()["reason"] == "worker_not_running"

            stamp_file.write_text("{corrupt", encoding="utf-8")
            assert client.get("/ready").status_code == 503

            write_liveness_stamp(stamp_file, progress=1, worker_id="pg-ready-worker")
            stale = time.time() - 3600.0
            os.utime(stamp_file, (stale, stale))
            assert client.get("/ready").status_code == 503

            # 2. Valid stamp -> 200 and warms cache.
            write_liveness_stamp(stamp_file, progress=2, worker_id="pg-ready-worker")
            res_ok = client.get("/ready")
            assert res_ok.status_code == 200
            assert res_ok.json()["worker"] is True
            assert probe.cached_worker_active() is True

            # 3. DB outage invalidates cache immediately across recovery.
            stamp_file.unlink()
            orig_get_engine = db_session.get_engine

            def _broken_engine(*_args, **_kwargs):
                raise OperationalError("SELECT 1", {}, Exception("pg outage"))

            monkeypatch.setattr("mail_core.db.session.get_engine", _broken_engine)
            res_outage = client.get("/ready")
            assert res_outage.status_code == 503
            assert res_outage.json()["reason"] == "database: OperationalError"
            assert probe.cached_worker_active() is None

            monkeypatch.setattr("mail_core.db.session.get_engine", orig_get_engine)
            res_recovered_no_stamp = client.get("/ready")
            assert res_recovered_no_stamp.status_code == 503
            assert res_recovered_no_stamp.json()["reason"] == "worker_not_running"

            # 4. Schema mismatch invalidates cache across recovery.
            write_liveness_stamp(stamp_file, progress=3, worker_id="pg-ready-worker")
            assert client.get("/ready").status_code == 200
            assert probe.cached_worker_active() is True

            stamp_file.unlink()
            from mail_core.api import app as app_mod

            orig_head = app_mod._code_schema_head
            monkeypatch.setattr("mail_core.api.app._code_schema_head", lambda: "20990101_0000")
            res_mismatch = client.get("/ready")
            assert res_mismatch.status_code == 503
            assert res_mismatch.json()["reason"] == "schema_out_of_date"
            assert probe.cached_worker_active() is None

            monkeypatch.setattr("mail_core.api.app._code_schema_head", orig_head)
            res_after_mismatch = client.get("/ready")
            assert res_after_mismatch.status_code == 503
            assert res_after_mismatch.json()["reason"] == "worker_not_running"

            # 5. Real PG LISTEN disconnect via pg_terminate_backend invalidates cache before /ready.
            write_liveness_stamp(stamp_file, progress=4, worker_id="pg-ready-worker")
            assert client.get("/ready").status_code == 200
            assert probe.cached_worker_active() is True
            stamp_file.unlink()

            with orig_get_engine().connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                pid = conn.execute(
                    text(
                        "SELECT pid FROM pg_stat_activity "
                        "WHERE datname = current_database() AND application_name = :app"
                    ),
                    {"app": app_name},
                ).scalar_one()
                conn.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": pid})

            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and (
                listener.listen_ready or probe.cached_worker_active() is not None
            ):
                time.sleep(0.02)
            assert listener.listen_ready is False
            assert probe.cached_worker_active() is None

            res_listen_down = client.get("/ready")
            assert res_listen_down.status_code == 503
            assert res_listen_down.json()["reason"] == "outbox_listener"

            # Wait for LISTEN to reconnect; missing stamp must still fail /ready (not cached True).
            assert listener.wait_started(5.0)
            res_listen_back = client.get("/ready")
            assert res_listen_back.status_code == 503
            assert res_listen_back.json()["reason"] == "worker_not_running"

            write_liveness_stamp(stamp_file, progress=6, worker_id="pg-ready-worker")
            assert client.get("/ready").status_code == 200

            # 6. Distributed mode (embedded=0, no explicit stamp) passes with DB heartbeat alone.
            stamp_file.unlink()
            monkeypatch.delenv("MAIL_CORE_LIVENESS_STAMP", raising=False)
            monkeypatch.delenv("MAIL_CORE_DATA_DIR", raising=False)
            monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "0")
            monkeypatch.setattr(liveness, "DEFAULT_STAMP_PATH", str(tmp_path / "absent-default.json"))
            probe.invalidate()
            res_dist = client.get("/ready")
            assert res_dist.status_code == 200
            assert res_dist.json()["worker"] is True

            assert not any("ROLLBACK" in stmt.upper() for stmt in executed_sql)
            assert non_idle_rollbacks == []
            assert not any(b"ROLLBACK" in cmd.upper() for cmd in wire_commands)
    finally:
        listener.stop(timeout=2.0)


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_finding7_pg_ready_ttl_expiry_and_zero_rollback_sql(monkeypatch, tmp_path):
    """AC-005: /ready caches worker check only until TTL expiry and emits zero ROLLBACKs."""
    Session = db_session.get_session_factory()
    with Session() as session:
        record_heartbeat(session, "pg-ttl-worker", active_jobs=0)
        session.commit()

    listener = OutboxListenThread(
        OutboxDispatcher(),
        dsn=_dsn_from_settings(),
        reconnect_s=0.5,
        idle_timeout_s=0.2,
    )
    listener.start()
    assert listener.wait_started(5.0)
    monkeypatch.setattr("mail_core.realtime.listener.get_outbox_listener", lambda: listener)

    short_probe = ReadinessProbe(ttl_s=0.15)
    monkeypatch.setattr("mail_core.readiness._probe", short_probe)

    stamp_file = tmp_path / "pg-ttl-liveness.json"
    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "1")
    monkeypatch.setenv("MAIL_CORE_REQUIRE_WORKER_READY", "1")
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(stamp_file))
    write_liveness_stamp(stamp_file, progress=1, worker_id="pg-ttl-worker")

    client = TestClient(app)
    try:
        with _track_ready_sql_and_wire_rollbacks(monkeypatch) as (
            executed_sql,
            non_idle_rollbacks,
            wire_commands,
        ):
            # First call misses cache -> queries alembic_version AND app_settings.
            assert client.get("/ready").status_code == 200
            heartbeat_queries_1 = sum(1 for s in executed_sql if "app_settings" in s)
            alembic_queries_1 = sum(1 for s in executed_sql if "alembic_version" in s)
            assert heartbeat_queries_1 == 1
            assert alembic_queries_1 == 1

            # Second call within TTL hits worker cache -> only alembic_version runs.
            assert client.get("/ready").status_code == 200
            heartbeat_queries_2 = sum(1 for s in executed_sql if "app_settings" in s)
            alembic_queries_2 = sum(1 for s in executed_sql if "alembic_version" in s)
            assert heartbeat_queries_2 == 1
            assert alembic_queries_2 == 2

            # After TTL expires and stamp disappears, /ready re-queries and fails with 503.
            time.sleep(0.2)
            stamp_file.unlink()
            res_expired = client.get("/ready")
            assert res_expired.status_code == 503
            assert res_expired.json()["reason"] == "worker_not_running"
            heartbeat_queries_3 = sum(1 for s in executed_sql if "app_settings" in s)
            assert heartbeat_queries_3 == 2

            assert not any("ROLLBACK" in stmt.upper() for stmt in executed_sql)
            assert non_idle_rollbacks == []
            assert not any(b"ROLLBACK" in cmd.upper() for cmd in wire_commands)

            # Control check: prove the spy is falsifiable (an ORM Session read triggers wire ROLLBACK).
            with Session() as control_session:
                control_session.execute(text("SELECT 1"))
            assert any(b"ROLLBACK" in cmd.upper() for cmd in wire_commands)
    finally:
        listener.stop(timeout=2.0)


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_ac006_sigkill_subprocess_crash_recovery(monkeypatch, tmp_path):
    """AC-006: SIGKILL subprocess preserves committed state, rolls back in-flight tx, rebuilds liveness."""
    Session = db_session.get_session_factory()
    acc_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    worker_id = f"sigkill-worker-{uuid.uuid4().hex[:8]}"
    stamp_file = tmp_path / "sigkill-liveness.json"
    child_app_name = f"kkmail_sigkill_{uuid.uuid4().hex[:8]}"

    with Session() as session:
        session.add(
            Account(
                id=acc_id,
                email=f"sigkill-{acc_id.hex[:6]}@example.com",
                provider="stub",
                sync_enabled=True,
            )
        )
        session.flush()
        session.add(
            Folder(
                id=folder_id,
                account_id=acc_id,
                remote_id="INBOX",
                name="INBOX",
                role="inbox",
            )
        )
        session.commit()

    child_code = """
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from mail_core.db.events import install_session_wake_hooks
from mail_core.liveness import write_liveness_stamp
from mail_core.mail.storage.models import (
    Message,
    MessageLocation,
    OutboxEvent,
    SyncCheckpoint,
)
from mail_core.worker.heartbeat import record_heartbeat

install_session_wake_hooks(Session)
db_url = os.environ["MAIL_CORE_DATABASE_URL"]
app_name = os.environ["KKMAIL_CHILD_APP_NAME"]
account_id = uuid.UUID(os.environ["KKMAIL_TEST_ACCOUNT_ID"])
folder_id = uuid.UUID(os.environ["KKMAIL_TEST_FOLDER_ID"])
worker_id = os.environ["KKMAIL_TEST_WORKER_ID"]
stamp_path = Path(os.environ["MAIL_CORE_LIVENESS_STAMP"])

engine = create_engine(
    db_url,
    future=True,
    poolclass=NullPool,
    connect_args={"application_name": app_name},
)
ChildSession = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# 1. Committed synchronous business transaction + heartbeat + local stamp.
with ChildSession() as s:
    msg = Message(
        account_id=account_id,
        remote_id="sigkill-committed-1",
        subject="Durable before SIGKILL",
        from_address="sender@example.com",
    )
    s.add(msg)
    s.flush()
    s.add(MessageLocation(message_id=msg.id, folder_id=folder_id, uid=42))
    s.add(
        SyncCheckpoint(
            account_id=account_id,
            folder_id=folder_id,
            cursor={"uid": 42},
            full_scan_complete=True,
            last_delta_settled_at=datetime.now(timezone.utc),
        )
    )
    s.add(
        OutboxEvent(
            event_type="sync.completed",
            account_id=account_id,
            payload={"committed": True},
        )
    )
    record_heartbeat(s, worker_id, active_jobs=1)
    s.commit()

write_liveness_stamp(stamp_path, progress=1, worker_id=worker_id)

# 2. Hold a second transaction uncommitted mid-flight until SIGKILL arrives.
inflight = ChildSession()
inflight_msg = Message(
    account_id=account_id,
    remote_id="sigkill-uncommitted-2",
    subject="Should roll back on SIGKILL",
    from_address="sender@example.com",
)
inflight.add(inflight_msg)
inflight.flush()
inflight.add(
    OutboxEvent(
        event_type="sync.uncommitted",
        account_id=account_id,
        payload={"committed": False},
    )
)
cp = inflight.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
cp.cursor = {"uid": 999}
inflight.flush()

print("READY", flush=True)
time.sleep(60)
"""

    child_env = os.environ.copy()
    repo_src = str(Path(__file__).resolve().parents[2] / "src")
    existing_pp = child_env.get("PYTHONPATH", "")
    child_env["PYTHONPATH"] = f"{repo_src}:{existing_pp}" if existing_pp else repo_src
    child_env["MAIL_CORE_LIVENESS_STAMP"] = str(stamp_file)
    child_env["KKMAIL_CHILD_APP_NAME"] = child_app_name
    child_env["KKMAIL_TEST_ACCOUNT_ID"] = str(acc_id)
    child_env["KKMAIL_TEST_FOLDER_ID"] = str(folder_id)
    child_env["KKMAIL_TEST_WORKER_ID"] = worker_id

    proc = subprocess.Popen(
        [sys.executable, "-c", child_code],
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready_queue: queue.Queue[str] = queue.Queue()

        def _read_ready() -> None:
            assert proc.stdout is not None
            ready_queue.put(proc.stdout.readline().strip())

        reader = threading.Thread(target=_read_ready, daemon=True)
        reader.start()
        try:
            line = ready_queue.get(timeout=15.0)
        except queue.Empty:
            stderr_out = proc.stderr.read() if proc.stderr is not None else ""
            pytest.fail(f"child process failed to signal READY (stderr={stderr_out!r})")
        assert line == "READY", f"unexpected child output: {line!r}"

        os.kill(proc.pid, signal.SIGKILL)
        returncode = proc.wait(timeout=5.0)
        assert returncode == -signal.SIGKILL
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5.0)
        if proc.stdout is not None:
            proc.stdout.close()
        if proc.stderr is not None:
            proc.stderr.close()

    # Wait briefly for PostgreSQL backend cleanup of the SIGKILLed socket.
    engine = db_session.get_engine()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            remaining = conn.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND application_name = :app"
                ),
                {"app": child_app_name},
            ).scalar_one()
        if int(remaining) == 0:
            break
        time.sleep(0.05)
    assert int(remaining) == 0

    # Verify committed business state survived cleanly and uncommitted tx rolled back.
    with Session() as session:
        committed_msg = session.scalar(
            select(Message).where(
                Message.account_id == acc_id,
                Message.remote_id == "sigkill-committed-1",
            )
        )
        assert committed_msg is not None
        assert committed_msg.subject == "Durable before SIGKILL"

        uncommitted_msg = session.scalar(
            select(Message).where(
                Message.account_id == acc_id,
                Message.remote_id == "sigkill-uncommitted-2",
            )
        )
        assert uncommitted_msg is None

        cp = session.get(SyncCheckpoint, {"account_id": acc_id, "folder_id": folder_id})
        assert cp is not None
        assert cp.cursor == {"uid": 42}
        assert cp.full_scan_complete is True
        assert cp.last_delta_settled_at is not None

        committed_outbox = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.account_id == acc_id,
                OutboxEvent.event_type == "sync.completed",
            )
        )
        uncommitted_outbox = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.account_id == acc_id,
                OutboxEvent.event_type == "sync.uncommitted",
            )
        )
        assert committed_outbox is not None
        assert uncommitted_outbox is None

        hb_row = session.get(AppSetting, f"{HEARTBEAT_PREFIX}{worker_id}")
        assert hb_row is not None

    # Simulate disposable heartbeat & tmpfs stamp loss across restart, then rebuild cleanly.
    with Session() as session:
        session.execute(
            AppSetting.__table__.delete().where(
                AppSetting.key == f"{HEARTBEAT_PREFIX}{worker_id}"
            )
        )
        session.commit()
    stamp_file.unlink(missing_ok=True)

    monkeypatch.setenv("MAIL_CORE_EMBEDDED_WORKER", "1")
    monkeypatch.setenv("MAIL_CORE_REQUIRE_WORKER_READY", "1")
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(stamp_file))

    active_lost, _ = read_worker_active_via_core(engine)
    assert active_lost is False

    rebuilt_worker_id = f"rebuilt-worker-{uuid.uuid4().hex[:8]}"
    with Session() as session:
        record_heartbeat(session, rebuilt_worker_id, active_jobs=0)
        session.commit()
    write_liveness_stamp(stamp_file, progress=1, worker_id=rebuilt_worker_id)

    active_rebuilt, lag_rebuilt = read_worker_active_via_core(engine)
    assert active_rebuilt is True
    assert lag_rebuilt is not None

    listener = OutboxListenThread(
        OutboxDispatcher(),
        dsn=_dsn_from_settings(),
        reconnect_s=0.5,
        idle_timeout_s=0.2,
    )
    listener.start()
    assert listener.wait_started(5.0)
    monkeypatch.setattr("mail_core.realtime.listener.get_outbox_listener", lambda: listener)
    try:
        res_ready = TestClient(app).get("/ready")
        assert res_ready.status_code == 200
        assert res_ready.json()["status"] == "ready"
        assert res_ready.json()["worker"] is True
    finally:
        listener.stop(timeout=2.0)
