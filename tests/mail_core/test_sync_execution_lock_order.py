"""DEFECT 2: refresh_requests must lock Targets before Requests.

The settlement lock order documented in ``mail_core.sync.execution`` is
WorkerJob row -> generation lock -> binding rows / Targets (UUID ascending)
-> Requests (UUID ascending). The old ``refresh_requests`` violated it: it
locked each SyncRequest row first and only then that request's Target rows.
Callers that already hold Target locks (``settle_job_bindings`` via
complete_job/fail_job) therefore wanted Requests while holding Targets,
whereas independent callers (``converge_orphaned_bindings``,
``mark_bindings_running``) reached ``refresh_requests`` holding no Target
locks and took Request locks first, then Target locks -- the two orders
deadlock in PostgreSQL (40P01).

These tests pin the *statement acquisition order* on a SQLite engine.
SQLite's dialect strips ``FOR UPDATE`` from rendered statements (verified:
the locking selects are emitted without the clause), so the tests match
the locking selects by table -- ``sync_request_targets`` vs
``sync_requests`` -- which are exactly the selects that carry
``FOR UPDATE`` on PostgreSQL, and assert the Targets select precedes the
Requests select. A true PostgreSQL deadlock repro is not possible in
this sandbox (no PG); statement order is the pinned invariant.

No existing test is modified by this file.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.storage.models import (
    OutboxEvent,
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.sync import execution as execution_mod
from mail_core.sync.execution import refresh_requests, settle_job_bindings

_DDL = [
    """
    CREATE TABLE sync_requests (
        id CHAR(36) PRIMARY KEY,
        client_request_id VARCHAR(64) NOT NULL UNIQUE,
        mode VARCHAR(32) NOT NULL,
        "trigger" VARCHAR(32) NOT NULL,
        state VARCHAR(32) NOT NULL DEFAULT 'queued',
        scope JSON NOT NULL DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        finished_at DATETIME
    )
    """,
    """
    CREATE TABLE sync_request_targets (
        id CHAR(36) PRIMARY KEY,
        request_id CHAR(36) NOT NULL,
        account_id CHAR(36),
        folder_id CHAR(36),
        target_key VARCHAR(255) NOT NULL,
        requested_generation CHAR(36) NOT NULL,
        state VARCHAR(32) NOT NULL DEFAULT 'queued',
        error_code VARCHAR(64),
        safe_error VARCHAR(500),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        finished_at DATETIME
    )
    """,
    """
    CREATE TABLE sync_request_target_jobs (
        id CHAR(36) PRIMARY KEY,
        target_id CHAR(36) NOT NULL,
        execution_generation CHAR(36) NOT NULL,
        job_id CHAR(36),
        phase VARCHAR(64) NOT NULL DEFAULT 'sync',
        folder_id CHAR(36),
        status VARCHAR(32) NOT NULL DEFAULT 'queued',
        error_code VARCHAR(64),
        safe_error VARCHAR(500),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        finished_at DATETIME
    )
    """,
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
    """,
    """
    CREATE TABLE worker_jobs (
        id CHAR(36) PRIMARY KEY,
        execution_generation CHAR(36) NOT NULL,
        job_type VARCHAR(64) NOT NULL,
        account_id CHAR(36),
        dedupe_key VARCHAR(128),
        payload JSON NOT NULL DEFAULT '{}',
        status VARCHAR(32) NOT NULL DEFAULT 'pending',
        priority INTEGER NOT NULL DEFAULT 100,
        run_after DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        failure_attempts INTEGER NOT NULL DEFAULT 0,
        locked_by VARCHAR(128),
        locked_at DATETIME,
        last_error TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
    )
    """,
]

_NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)


def _make_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    return engine


def _seed_request(Session, *, binding_status: str):
    """One request + one target + one binding; returns (request_id, generation)."""
    request_id = uuid.uuid4()
    target_id = uuid.uuid4()
    generation = uuid.uuid4()
    with Session() as session:
        session.add(
            SyncRequest(
                id=request_id,
                client_request_id=f"lock-order-{uuid.uuid4().hex}",
                mode="delta",
                trigger="manual",
                state="queued",
                scope={},
                created_at=_NOW,
            )
        )
        session.add(
            SyncRequestTarget(
                id=target_id,
                request_id=request_id,
                target_key=f"folder:{uuid.uuid4().hex}",
                requested_generation=generation,
                state="queued",
                created_at=_NOW,
            )
        )
        session.add(
            SyncRequestTargetJob(
                id=uuid.uuid4(),
                target_id=target_id,
                execution_generation=generation,
                job_id=None,
                phase="sync",
                status=binding_status,
                created_at=_NOW,
                finished_at=_NOW if binding_status in ("complete", "failed") else None,
            )
        )
        session.commit()
    return request_id, generation


class _Capture:
    """before_cursor_execute listener recording executed statements."""

    def __init__(self, engine):
        self.engine = engine
        self.statements: list[str] = []

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._record)
        return False

    def _record(self, _conn, _cursor, statement, _params, _context, _many):
        self.statements.append(statement)


def _first_select_index(statements: list[str], table: str) -> int | None:
    """Index of the first SELECT ... FROM <table> in ``statements``.

    Word-boundary match so ``sync_request_targets`` does not match
    ``sync_request_target_jobs`` and vice versa.
    """
    pattern = re.compile(rf"\bfrom\s+{re.escape(table)}\b")
    for index, statement in enumerate(statements):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and pattern.search(normalized):
            return index
    return None


def _assert_targets_locked_before_requests(statements: list[str]) -> None:
    targets_index = _first_select_index(statements, "sync_request_targets")
    requests_index = _first_select_index(statements, "sync_requests")
    assert targets_index is not None, (
        f"no select against sync_request_targets captured: {statements!r}"
    )
    assert requests_index is not None, (
        f"no select against sync_requests captured: {statements!r}"
    )
    assert targets_index < requests_index, (
        "lock acquisition order violated: the first (FOR UPDATE on PG) "
        "select against sync_requests precedes the first (FOR UPDATE on PG) "
        f"select against sync_request_targets: {statements!r}"
    )


def test_refresh_requests_locks_targets_before_requests_direct():
    """(a) Direct / independent entry point: refresh_requests alone."""
    engine = _make_engine()
    Session = sessionmaker(bind=engine)
    first_id, _ = _seed_request(Session, binding_status="complete")
    second_id, _ = _seed_request(Session, binding_status="complete")

    with _Capture(engine) as capture:
        with Session() as session:
            # Deliberately pass ids out of order: global UUID-ascending
            # acquisition must hold regardless of caller ordering.
            refresh_requests(session, [second_id, first_id])
            session.commit()
        captured = list(capture.statements)

    _assert_targets_locked_before_requests(captured)

    # Semantics preserved: both requests aggregate to complete with Outbox.
    with Session() as session:
        for request_id in (first_id, second_id):
            req = session.get(SyncRequest, request_id)
            assert req is not None and req.state == "complete"
            assert req.finished_at is not None
        events = list(session.scalars(select(OutboxEvent)).all())
        assert {e.payload.get("request_id") for e in events} == {
            str(first_id),
            str(second_id),
        }
        assert all(e.payload.get("state") == "complete" for e in events)


def test_refresh_requests_locks_targets_before_requests_via_settle_path():
    """(b) Settlement entry point: settle_job_bindings + refresh_requests.

    This is the complete_job/fail_job path in jobs.py: settle locks
    bindings/Targets and returns request ids, then the caller persists
    aggregation via refresh_requests in the same transaction. The
    refresh phase must follow the same Targets -> Requests order, and
    the combined sequence must never take a Request lock before a
    Target lock.
    """
    engine = _make_engine()
    Session = sessionmaker(bind=engine)
    request_id, generation = _seed_request(Session, binding_status="queued")
    job_id = uuid.uuid4()
    with Session() as session:
        session.add(
            WorkerJob(
                id=job_id,
                execution_generation=generation,
                job_type="sync_folder_delta",
                payload={},
                status="claimed",
                run_after=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        # Point the seeded binding at the job (settle keys off generation,
        # but keep the fixture faithful to a claimed execution).
        binding = session.scalar(select(SyncRequestTargetJob))
        assert binding is not None
        binding.job_id = job_id
        session.commit()

    with _Capture(engine) as capture:
        with Session() as session:
            job = session.get(WorkerJob, job_id)
            assert job is not None
            capture.statements.clear()
            # lock_generation issues a PostgreSQL advisory-lock statement
            # that SQLite cannot execute; the lock-order invariant under
            # test is the Targets -> Requests order after that point.
            with patch.object(
                execution_mod, "lock_generation", lambda _session, _gen: None
            ):
                request_ids = settle_job_bindings(session, job, outcome="complete")
                during_settle = list(capture.statements)
                capture.statements.clear()
                refresh_requests(session, request_ids)
                during_refresh = list(capture.statements)
            session.commit()

    assert request_ids == {request_id}
    # Settle itself locks Targets and takes no Request lock at all.
    assert _first_select_index(during_settle, "sync_request_targets") is not None
    assert _first_select_index(during_settle, "sync_requests") is None
    # The refresh phase reached from the settle path follows the same
    # global order as the direct path.
    _assert_targets_locked_before_requests(during_refresh)
    # Combined settle + refresh sequence: first Target lock precedes
    # first Request lock.
    _assert_targets_locked_before_requests(during_settle + during_refresh)

    with Session() as session:
        req = session.get(SyncRequest, request_id)
        assert req is not None and req.state == "complete"
        assert req.finished_at is not None
