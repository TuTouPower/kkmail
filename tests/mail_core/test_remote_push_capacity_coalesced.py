"""Capacity-deferred remote push must keep an executable followup.

When ``push_remote_operations`` hits the connection budget, it resets
the op to PENDING and re-enqueues the push under the same dedupe key
``remote-op-push:{account_id}`` -- the job currently executing IS that
job (CLAIMED), so ``enqueue_job`` coalesces the followup into the
running job's ``_queue_next`` payload and returns the CLAIMED row.
The handler then completes the current job via ``complete_job``, which
creates the successor from ``_queue_next`` ONLY when the followup was
not already scheduled as an independent job
(``followup_scheduled and not followup_coalesced`` in jobs.py).

The bug: the capacity branch discarded the ``enqueue_job`` return
value and reported only ``followup_scheduled=True``, so settlement
concluded an independent successor already existed, marked the job
DONE and stripped ``_queue_*`` from its payload -- destroying the
coalesced followup. The op stayed PENDING with zero active jobs.

This test drives the real chain on PostgreSQL: seed a CLAIMED push job + a PENDING
op, make the provider raise ``ProviderCapacityUnavailable``, run
``push_remote_operations``, then settle with ``complete_job`` exactly
as the handler does, and assert a PENDING successor survives.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobStatus, JobType, RemoteOperationStatus
from mail_core.mail.storage.models import Account, RemoteOperation, WorkerJob
from mail_core.providers.connection_slots import ProviderCapacityUnavailable
from mail_core.sync import remote_push as remote_push_mod
from mail_core.sync.jobs import complete_job

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
_WORKER = "w-push"


class _CapacityProvider:
    name = "memory"

    def apply_remote_operation(self, _op_type, _desired_state):
        raise ProviderCapacityUnavailable("connection budget saturated")


def test_capacity_coalesced_followup_survives_settlement():
    Session = get_session_factory()
    account_id = uuid.uuid4()
    job_id = uuid.uuid4()
    op_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(
                id=account_id,
                email=f"push-{uuid.uuid4().hex[:8]}@example.test",
                provider="memory",
                credential_ref="ref",
                config={},
                sync_enabled=True,
            )
        )
        # The currently executing push job (claimed by the worker that
        # will run push_remote_operations).
        session.add(
            WorkerJob(
                id=job_id,
                execution_generation=uuid.uuid4(),
                job_type=JobType.REMOTE_OPERATION_PUSH.value,
                account_id=account_id,
                payload={},
                status=JobStatus.CLAIMED.value,
                locked_by=_WORKER,
                locked_at=_NOW,
                dedupe_key=f"remote-op-push:{account_id}",
                run_after=_NOW,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.add(
            RemoteOperation(
                id=op_id,
                account_id=account_id,
                entity_key="message:msg-1",
                op_type="move",
                desired_state={"remote_id": "msg-1", "folder_remote_id": "Archive"},
                status=RemoteOperationStatus.PENDING.value,
                created_at=_NOW,
                updated_at=_NOW,
            )
        )
        session.commit()

    with patch.object(remote_push_mod, "build_provider", lambda *a, **k: _CapacityProvider()):
        result = remote_push_mod.push_remote_operations(
            account_id, worker_id=_WORKER, store=object()
        )

    assert result["status"] == "capacity_unavailable"
    assert result["followup_scheduled"] is True
    # The enqueue coalesced into the running job: the result must say so,
    # or complete_job will treat the followup as an independent job.
    assert result.get("followup_coalesced") is True

    with Session() as session:
        op = session.get(RemoteOperation, op_id)
        assert op is not None and op.status == RemoteOperationStatus.PENDING.value
        assert op.next_attempt_at is not None
        job = session.get(WorkerJob, job_id)
        assert job is not None
        assert (job.payload or {}).get("_queue_next") is not None

    # Settle exactly as the handler does for capacity_unavailable.
    with Session() as session:
        job = session.get(WorkerJob, job_id)
        assert job is not None
        successor = complete_job(session, job, worker_id=_WORKER, result=result)
        session.commit()
        assert successor is not None, (
            "settlement destroyed the coalesced followup: no successor job"
        )
        assert successor.status == JobStatus.PENDING.value
        assert successor.dedupe_key == f"remote-op-push:{account_id}"

    with Session() as session:
        jobs = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.dedupe_key == f"remote-op-push:{account_id}"
                )
            ).all()
        )
        by_status = {}
        for j in jobs:
            by_status.setdefault(j.status, []).append(j)
        assert len(by_status.get(JobStatus.DONE.value, [])) == 1
        pending = by_status.get(JobStatus.PENDING.value, [])
        assert len(pending) == 1, "the deferred push must remain executable"
        op = session.get(RemoteOperation, op_id)
        assert op is not None and op.status == RemoteOperationStatus.PENDING.value
