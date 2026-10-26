"""Orphan patrol must recheck live generations at decision time.

``converge_orphaned_bindings`` snapshots the live-generation set first
and reads open bindings afterwards. A request binding a CLAIMED job
commits ``ensure_successor_generation`` (the successor generation lands
in the job's ``_queue_next`` payload) and its ``job_id``-NULL binding in
ONE transaction: if that transaction commits between the patrol's
snapshot and its binding read, the patrol sees the new binding but not
its generation and fails a healthy queued request as
``execution_lost``.

The pinned invariant: before condemning a ``job_id``-NULL binding on a
snapshot miss, the patrol recomputes the live set at decision time;
only a binding whose generation is STILL not live is orphaned.

The race is simulated by making the first live-set computation return
a stale (pre-bind) snapshot while the decision-time recheck computes
the real set from the database, following the raw-DDL SQLite pattern
of test_sync_orphan_patrol_live_generations.py. No existing test is
modified by this file.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.domain.enums import JobStatus
from mail_core.mail.storage.models import (
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.sync import execution as execution_mod
from mail_core.sync.execution import converge_orphaned_bindings

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


def _seed_binding(Session, *, generation: uuid.UUID) -> uuid.UUID:
    """One request + target + open job_id-NULL binding at ``generation``."""
    binding_id = uuid.uuid4()
    request_id = uuid.uuid4()
    target_id = uuid.uuid4()
    with Session() as session:
        session.add(
            SyncRequest(
                id=request_id,
                client_request_id=f"patrol-race-{uuid.uuid4().hex}",
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
                id=binding_id,
                target_id=target_id,
                execution_generation=generation,
                job_id=None,
                phase="sync",
                status="queued",
                created_at=_NOW,
            )
        )
        session.commit()
    return binding_id


def test_patrol_rechecks_live_generations_before_failing_successor_binding():
    engine = _make_engine()
    Session = sessionmaker(bind=engine)

    running_generation = uuid.uuid4()
    successor_generation = uuid.uuid4()
    orphan_generation = uuid.uuid4()

    # A CLAIMED job whose successor generation was pre-allocated when a
    # new request bound it (the bind committed after the patrol's
    # snapshot was taken).
    with Session() as session:
        session.add(
            WorkerJob(
                id=uuid.uuid4(),
                execution_generation=running_generation,
                job_type="sync_folder_delta",
                payload={
                    "_queue_next": {"execution_generation": str(successor_generation)}
                },
                status=JobStatus.CLAIMED.value,
                run_after=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()
    successor_binding_id = _seed_binding(Session, generation=successor_generation)
    orphan_binding_id = _seed_binding(Session, generation=orphan_generation)

    real_impl = execution_mod._live_execution_generations
    calls = {"n": 0}

    def stale_first_snapshot(session):
        calls["n"] += 1
        if calls["n"] == 1:
            # The snapshot predates the bind commit: it cannot contain
            # the successor generation (nor the running one).
            return set()
        return real_impl(session)

    with Session() as session:
        with patch.object(
            execution_mod, "_live_execution_generations", stale_first_snapshot
        ):
            changed = converge_orphaned_bindings(session)
        session.commit()

    # Only the genuinely orphaned binding converged.
    assert changed == 1
    with Session() as session:
        bindings = {b.id: b for b in session.scalars(select(SyncRequestTargetJob)).all()}
        successor_binding = bindings[successor_binding_id]
        assert successor_binding.status == "queued"
        assert successor_binding.error_code is None
        assert successor_binding.finished_at is None

        orphan_binding = bindings[orphan_binding_id]
        assert orphan_binding.status == "failed"
        assert orphan_binding.error_code == "execution_lost"
        assert orphan_binding.finished_at is not None
