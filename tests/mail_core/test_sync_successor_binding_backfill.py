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

Runs against the real PostgreSQL schema created by ``alembic upgrade head``:
``complete_job`` / ``claim_jobs`` take real FOR UPDATE / SKIP LOCKED row
locks and the settlement path uses the real generation advisory lock.
The invariant under test is the backfilled ``job_id`` and the subsequent
claim-time transition to ``running``.

No existing test is modified by this file.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import (
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.sync.execution import bind_target
from mail_core.sync.jobs import claim_jobs, complete_job

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_WORKER = "w-defect3"


def test_complete_job_backfills_successor_job_id_onto_preallocated_bindings():
    Session = get_session_factory()

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

    with Session() as session:
        claimed = claim_jobs(session, worker_id=_WORKER, limit=1, now=_NOW)
        assert [j.id for j in claimed] == [successor_id]
        session.commit()

    with Session() as session:
        binding = session.scalar(select(SyncRequestTargetJob))
        assert binding is not None
        assert binding.job_id == successor_id
        assert binding.status == "running"
