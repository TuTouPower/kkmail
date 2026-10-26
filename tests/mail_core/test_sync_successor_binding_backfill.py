"""DEFECT 3: complete_job must backfill successor job_id onto pre-allocated bindings.

When a request arrives while its job is CLAIMED, ``execution.bind_target``
pre-binds its targets to the successor generation pre-allocated in the
job's ``_queue_next`` payload, with ``job_id = NULL`` (there is no
successor job row yet). ``complete_job`` creates the successor with
exactly that generation but (before this fix) never backfilled those
rows, so their ``job_id`` stayed NULL. ``mark_bindings_running``
(claim-time hook) finds bindings by ``job_id IN (claimed job ids)``;
NULL-job_id bindings are never matched, so they stayed ``queued``
while the successor actually executed.

The in-tree PostgreSQL test
``test_sync_execution_tracking.py::test_claimed_job_request_binds_successor_not_running_execution``
asserts ``binding.job_id == successor.id``, but it is skipped in unit
mode (no ``MAIL_CORE_DATABASE_URL`` in this sandbox), so no candidate
sync test fails in a unit-mode run at HEAD. This file pins the same
invariant on a SQLite engine, following
``test_sync_execution_lock_order.py``: SQLite strips ``FOR UPDATE``
and cannot execute the PostgreSQL advisory generation lock, so
``lock_generation`` is patched out -- the invariant under test is the
backfilled ``job_id`` and the subsequent claim-time transition to
``running``, neither of which depends on that lock.

No existing test is modified by this file.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.storage.models import (
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.sync import execution as execution_mod
from mail_core.sync.execution import bind_target
from mail_core.sync.jobs import claim_jobs, complete_job

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

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_WORKER = "w-defect3"


def _make_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    return engine


def test_complete_job_backfills_successor_job_id_onto_preallocated_bindings():
    engine = _make_engine()
    Session = sessionmaker(bind=engine)

    successor_generation = uuid.uuid4()
    job_id = uuid.uuid4()
    target_id = uuid.uuid4()

    with Session() as session:
        request_id = uuid.uuid4()
        session.add(
            SyncRequest(
                id=request_id,
                client_request_id=f"defect3-{uuid.uuid4().hex}",
                mode="delta",
                trigger="manual",
                state="queued",
                scope={},
                created_at=_NOW,
            )
        )
        target = SyncRequestTarget(
            id=target_id,
            request_id=request_id,
            target_key=f"folder:{uuid.uuid4().hex}",
            requested_generation=successor_generation,
            state="queued",
            created_at=_NOW,
        )
        session.add(target)
        session.add(
            WorkerJob(
                id=job_id,
                execution_generation=uuid.uuid4(),
                job_type="sync_folder_delta",
                payload={
                    "folder_id": "f-1",
                    "_queue_next": {
                        "payload": {"folder_id": "f-1"},
                        "priority": 10,
                        "run_after": _NOW.isoformat(),
                        "execution_generation": str(successor_generation),
                    },
                },
                status="claimed",
                priority=50,
                run_after=_NOW,
                locked_by=_WORKER,
                locked_at=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.flush()
        # As bind_target does for a request arriving mid-claim: bind to
        # the pre-allocated successor generation with job_id NULL.
        binding = bind_target(
            session,
            target=target,
            execution_generation=successor_generation,
            job=None,
        )
        assert binding.job_id is None
        assert binding.status == "queued"
        session.commit()

    with Session() as session:
        job = session.get(WorkerJob, job_id)
        assert job is not None
        with patch.object(
            execution_mod, "lock_generation", lambda _session, _gen: None
        ):
            successor = complete_job(session, job, worker_id=_WORKER)
            assert successor is not None
            assert successor.execution_generation == successor_generation
            successor_id = successor.id
            session.commit()

    with Session() as session:
        binding = session.scalar(select(SyncRequestTargetJob))
        assert binding is not None
        assert binding.job_id == successor_id
        assert binding.status == "queued"

    # Claiming the successor must flip the binding to running via
    # mark_bindings_running (which matches on job_id).
    with Session() as session:
        claimed = claim_jobs(session, worker_id=_WORKER, limit=1, now=_NOW)
        assert [j.id for j in claimed] == [successor_id]
        session.commit()

    with Session() as session:
        binding = session.scalar(select(SyncRequestTargetJob))
        assert binding is not None
        assert binding.job_id == successor_id
        assert binding.status == "running"
