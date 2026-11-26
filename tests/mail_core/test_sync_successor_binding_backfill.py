"""T082: a waiting target's link migrates to the successor job.

When a request arrives while its job is CLAIMED, the link points at that
real job and is marked ``needs_successor``. ``complete_job`` creates the
successor first and moves the link onto it in the same transaction, so the
link never references a planned-but-absent execution.
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
_WORKER = "w-t082-links"


def test_complete_job_migrates_waiting_link_to_real_successor():
    Session = get_session_factory()
    job_id = uuid.uuid4()
    target_id = uuid.uuid4()

    with Session() as session:
        request_id = uuid.uuid4()
        session.add(
            SyncRequest(
                id=request_id,
                client_request_id=f"t082-links-{uuid.uuid4().hex}",
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
            requested_generation=uuid.uuid4(),
            state="queued",
            created_at=_NOW,
        )
        session.add(target)
        session.add(
            WorkerJob(
                id=job_id,
                job_type="sync_folder_delta",
                payload={"folder_id": "f-1"},
                status="claimed",
                priority=50,
                run_after=_NOW,
                locked_by=_WORKER,
                locked_at=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
                execution_origin="foreground",
            )
        )
        session.flush()
        link = bind_target(session, target=target, job=session.get(WorkerJob, job_id))
        assert link.job_id == job_id
        assert link.needs_successor is True
        session.commit()

    with Session() as session:
        job = session.get(WorkerJob, job_id)
        successor = complete_job(session, job, worker_id=_WORKER)
        assert successor is not None
        successor_id = successor.id
        session.commit()

    with Session() as session:
        link = session.scalar(select(SyncRequestTargetJob))
        assert link is not None
        assert link.job_id == successor_id
        assert link.needs_successor is False
        assert link.status == "queued"

    from datetime import timedelta

    with Session() as session:
        claimed = claim_jobs(
            session, worker_id=_WORKER, limit=1,
            now=datetime.now(timezone.utc) + timedelta(seconds=1),
        )
        assert [j.id for j in claimed] == [successor_id]
        session.commit()

    with Session() as session:
        link = session.scalar(select(SyncRequestTargetJob))
        assert link is not None
        assert link.job_id == successor_id
        assert link.status == "running"
