"""R07: unified lock order — Targets before Bindings at every entry point.

The settlement path used to lock Binding rows before Targets while
``fail_open_targets`` (account/folder deletion) locked Targets before
Bindings; the inverted orders deadlocked on real PostgreSQL (40P01).
Both paths — and the claim/reclaim/patrol helpers — now take planning
reads first, then lock the FULL Target set of every affected request
(UUID ascending), and only then lock Binding rows.

As in test_sync_settlement_target_prelock.py, SQLite strips FOR UPDATE,
so locking selects are identified as entity selects (they render every
mapped column) captured via before_cursor_execute. The pinned invariant:
in each entry point's statement stream, the first Target entity select
precedes the first Binding entity select.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.storage.models import (
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from unittest.mock import patch

from mail_core.sync import execution as execution_mod
from mail_core.sync.execution import fail_open_targets, settle_job_bindings

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


class _Capture:
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
        self.statements.append(" ".join(str(statement).lower().split()))


def _first_entity_select(statements: list[str], table: str) -> int | None:
    # An entity (locking) select renders the full mapped column list, which
    # starts with "<table>.id, <table>."; planning reads select single
    # columns and never match this prefix.
    prefix = f"select {table}.id, {table}."
    for i, s in enumerate(statements):
        if s.startswith(prefix):
            return i
    return None


def _seed(Session):
    account_id = uuid.uuid4()
    request_id = uuid.uuid4()
    generation = uuid.uuid4()
    job_id = uuid.uuid4()
    target_id = uuid.uuid4()
    with Session() as session:
        session.add(
            SyncRequest(
                id=request_id, client_request_id=f"r07-{uuid.uuid4().hex}",
                mode="delta", trigger="manual", state="running", scope={},
                created_at=_NOW,
            )
        )
        session.add(
            SyncRequestTarget(
                id=target_id, request_id=request_id, account_id=account_id,
                target_key=f"folder:{target_id}", requested_generation=generation,
                state="running", created_at=_NOW,
            )
        )
        session.add(
            SyncRequestTargetJob(
                id=uuid.uuid4(), target_id=target_id,
                execution_generation=generation, job_id=job_id, phase="sync",
                status="running", created_at=_NOW,
            )
        )
        job = WorkerJob(
            id=job_id, execution_generation=generation,
            job_type="sync_folder_delta", payload={}, status="claimed",
            run_after=_NOW, created_at=_NOW, updated_at=_NOW,
        )
        session.add(job)
        session.commit()
    return account_id, job_id


def _assert_targets_before_bindings(statements: list[str]) -> None:
    target_idx = _first_entity_select(statements, "sync_request_targets")
    binding_idx = _first_entity_select(statements, "sync_request_target_jobs")
    assert target_idx is not None, f"no Target entity select in {statements}"
    assert binding_idx is not None, f"no Binding entity select in {statements}"
    assert target_idx < binding_idx, (
        f"Target lock must precede Binding lock:\n" + "\n".join(statements)
    )


def test_settle_locks_targets_before_bindings():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    Session = sessionmaker(bind=engine)
    _account_id, job_id = _seed(Session)
    with _Capture(engine) as cap, Session() as session:
        job = session.get(WorkerJob, job_id)
        assert job is not None
        cap.statements.clear()
        with patch.object(execution_mod, "lock_generation", lambda _s, _g: None):
            settle_job_bindings(session, job, outcome="complete")
        session.commit()
    _assert_targets_before_bindings(cap.statements)


def test_fail_open_targets_locks_targets_before_bindings():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    Session = sessionmaker(bind=engine)
    account_id, _job_id = _seed(Session)
    with _Capture(engine) as cap, Session() as session:
        fail_open_targets(
            session,
            account_id=account_id,
            error_code="account_deleted",
            safe_error="Account was deleted before the sync completed",
        )
        session.commit()
    _assert_targets_before_bindings(cap.statements)
