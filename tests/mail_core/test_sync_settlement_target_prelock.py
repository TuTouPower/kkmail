"""Multi-target settlement must pre-lock the full target set (deadlock fix).

``refresh_requests`` locks ALL targets of the affected requests in UUID
ascending order, then the requests. That alone does not prevent a
deadlock between two workers settling different jobs of the SAME
request: each settler first locked only its own job's target subset in
``settle_job_bindings`` and then entered ``refresh_requests`` already
holding a member of the set — the holder of the higher target waits on
the lower one while the holder of the lower one waits on the higher
(PostgreSQL 40P01).

The pinned invariant: ``settle_job_bindings`` must lock every target of
every affected request (one UUID-ascending FOR UPDATE select keyed by
``request_id``) BEFORE locking only the job's own subset — a settler
never waits on a target while already holding another target of the
same request set. Planning reads that merely map target -> request are
non-locking and are ignored here (they select only the ``request_id``
column, never the full entity).

As in test_sync_execution_lock_order.py, SQLite strips FOR UPDATE, so
locking selects are identified as the entity selects (they render every
mapped column, e.g. ``target_key``) against ``sync_request_targets``.
A true PostgreSQL deadlock repro needs a live PG; statement order is
the pinned invariant.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import sessionmaker

from mail_core.mail.storage.models import (
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

# Fixed UUIDs with a known global order: LOW must sort before HIGH.
_LOW = uuid.UUID("00000000-0000-0000-0000-000000000001")
_HIGH = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _make_engine():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        for ddl in _DDL:
            conn.execute(text(ddl))
    return engine


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


def _target_entity_selects(statements: list[str]) -> list[str]:
    """Entity selects against sync_request_targets (they render target_key)."""
    return [
        s
        for s in statements
        if s.startswith("select")
        and re.search(r"\bfrom\s+sync_request_targets\b", s)
        and "target_key" in s
    ]


def test_settle_prelocks_all_targets_of_affected_requests():
    """A job bound only to the HIGH target must still lock LOW first-hand:
    settle must issue one full-set lock keyed by request_id, and must not
    issue a subset-only (id IN) entity lock before it."""
    engine = _make_engine()
    Session = sessionmaker(bind=engine)
    request_id = uuid.uuid4()
    generation = uuid.uuid4()
    other_generation = uuid.uuid4()
    job_id = uuid.uuid4()
    with Session() as session:
        session.add(
            SyncRequest(
                id=request_id,
                client_request_id=f"prelock-{uuid.uuid4().hex}",
                mode="delta",
                trigger="manual",
                state="running",
                scope={},
                created_at=_NOW,
            )
        )
        for target_id in (_LOW, _HIGH):
            session.add(
                SyncRequestTarget(
                    id=target_id,
                    request_id=request_id,
                    target_key=f"folder:{target_id}",
                    requested_generation=generation,
                    state="running",
                    created_at=_NOW,
                )
            )
        # The job being settled observes only the HIGH target.
        session.add(
            SyncRequestTargetJob(
                id=uuid.uuid4(),
                target_id=_HIGH,
                execution_generation=generation,
                job_id=job_id,
                phase="sync",
                status="running",
                created_at=_NOW,
            )
        )
        # LOW was already settled complete by another execution.
        session.add(
            SyncRequestTargetJob(
                id=uuid.uuid4(),
                target_id=_LOW,
                execution_generation=other_generation,
                job_id=None,
                phase="sync",
                status="complete",
                created_at=_NOW,
                finished_at=_NOW,
            )
        )
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
        session.commit()

    with _Capture(engine) as capture:
        with Session() as session:
            job = session.get(WorkerJob, job_id)
            assert job is not None
            capture.statements.clear()
            with patch.object(
                execution_mod, "lock_generation", lambda _session, _gen: None
            ):
                request_ids = settle_job_bindings(session, job, outcome="complete")
                during_settle = list(capture.statements)
                refresh_requests(session, request_ids)
            session.commit()

    assert request_ids == {request_id}
    entity_selects = _target_entity_selects(during_settle)
    assert entity_selects, f"no target entity select captured: {during_settle!r}"
    full_set = [
        s for s in entity_selects if re.search(r"sync_request_targets\.request_id\s+in", s)
    ]
    subset_only = [
        s
        for s in entity_selects
        if re.search(r"sync_request_targets\.id\s+in", s)
        and not re.search(r"sync_request_targets\.request_id\s+in", s)
    ]
    assert full_set, (
        "settle never locked the full target set of the affected request; "
        f"entity selects were: {entity_selects!r}"
    )
    first_full = entity_selects.index(full_set[0])
    for stmt in subset_only:
        assert entity_selects.index(stmt) > first_full, (
            "settle locked a subset of targets before the full request set: "
            f"{entity_selects!r}"
        )

    # Semantics preserved: the job's binding completed and the request
    # aggregates to complete (LOW binding was already complete).
    with Session() as session:
        req = session.get(SyncRequest, request_id)
        assert req is not None and req.state == "complete"
        assert req.finished_at is not None
        binding = session.scalar(
            select(SyncRequestTargetJob).where(
                SyncRequestTargetJob.execution_generation == generation
            )
        )
        assert binding is not None and binding.status == "complete"
