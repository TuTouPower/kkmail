"""R04: delta CursorInvalidError must not complete the original request early.

Pre-fix, ``sync_folder_delta`` enqueued the metadata rebuild and returned
only ``followup_scheduled``; settlement marked the delta job's bindings
complete, so the originating sync request aggregated to "complete" while
the folder was still stale — and if the rebuild later failed, nothing fed
that failure back to the request.

Post-fix the result mirrors the engine's metadata branch
(``followup_coalesced``) and carries ``await_initialization`` so
settlement transfers the binding to the rebuild execution chain
(``_bind_initialization``): the request stays open until the rebuild
completes, and a terminal rebuild failure fails the request.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select

import mail_core.sync.delta as delta_mod
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobStatus, JobType
from mail_core.mail.storage.models import (
    Account,
    Folder,
    SyncCheckpoint,
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.providers.http import CursorInvalidError
from mail_core.sync.delta import sync_folder_delta
from mail_core.sync.execution import bind_target
from mail_core.sync.jobs import complete_job, fail_job

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


class _InvalidCursorProvider:
    def delta_changes(self, _remote_id, _cursor):
        raise CursorInvalidError("cursor expired")


@pytestmark_db
def test_delta_cursor_invalid_keeps_request_open_until_rebuild_settles(monkeypatch):
    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"r04-{uuid.uuid4().hex}@example.test", provider="imap")
        session.add(account)
        session.flush()
        folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        session.add(
            SyncCheckpoint(
                account_id=account.id,
                folder_id=folder.id,
                full_scan_complete=True,
                cursor={"uid_next": 2},
            )
        )
        delta_job = WorkerJob(
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            account_id=account.id,
            payload={"folder_id": str(folder.id)},
            status=JobStatus.CLAIMED.value,
            locked_by="delta-worker",
            dedupe_key=f"delta:{account.id}:{folder.id}",
        )
        session.add(delta_job)
        session.flush()
        request = SyncRequest(
            id=uuid.uuid4(),
            client_request_id=f"r04-{uuid.uuid4().hex}",
            mode="delta",
            trigger="manual",
            state="running",
            scope={},
        )
        session.add(request)
        session.flush()
        target = SyncRequestTarget(
            id=uuid.uuid4(),
            request_id=request.id,
            account_id=account.id,
            folder_id=folder.id,
            target_key=f"folder:{folder.id}",
            requested_generation=delta_job.execution_generation,
            state="running",
        )
        session.add(target)
        session.flush()
        bind_target(
            session,
            target=target,
            execution_generation=delta_job.execution_generation,
            job=delta_job,
            phase="delta",
            folder_id=folder.id,
            status="running",
        )
        session.commit()
        account_id, folder_id = account.id, folder.id
        delta_job_id, request_id, target_id = delta_job.id, request.id, target.id

    monkeypatch.setattr(
        delta_mod,
        "build_provider",
        lambda _account, _store=None, **_kwargs: _InvalidCursorProvider(),
    )
    result = sync_folder_delta(account_id, folder_id, worker_id="delta-worker", store=object())

    assert result["status"] == "cursor_invalid"
    assert result["followup_scheduled"] is True
    assert result["followup_coalesced"] is False
    assert result["await_initialization"] is True

    # Worker completion of the delta job: the request must NOT complete —
    # its binding transfers to the rebuild (metadata) job instead.
    with Session() as session:
        job = session.get(WorkerJob, delta_job_id)
        assert job is not None
        complete_job(session, job, worker_id="delta-worker", result=result)
        session.commit()

    with Session() as session:
        request = session.get(SyncRequest, request_id)
        target = session.get(SyncRequestTarget, target_id)
        assert request is not None and request.state == "running", (
            f"request settled early as {request.state if request else None!r}"
        )
        assert target is not None and target.state == "running"
        rebuild = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == account_id,
                WorkerJob.job_type == JobType.SYNC_FOLDER_METADATA.value,
                WorkerJob.status == JobStatus.PENDING.value,
            )
        )
        assert rebuild is not None
        transferred = session.scalar(
            select(SyncRequestTargetJob).where(
                SyncRequestTargetJob.target_id == target_id,
                SyncRequestTargetJob.phase == "initialization",
                SyncRequestTargetJob.status == "queued",
            )
        )
        assert transferred is not None, "binding was not transferred to the rebuild chain"
        assert transferred.execution_generation == rebuild.execution_generation
        rebuild_id = rebuild.id

    # A terminal rebuild failure must feed back: the original request fails.
    with Session() as session:
        rebuild = session.get(WorkerJob, rebuild_id)
        assert rebuild is not None
        rebuild.status = JobStatus.CLAIMED.value
        rebuild.locked_by = "meta-worker"
        session.commit()
    with Session() as session:
        rebuild = session.get(WorkerJob, rebuild_id)
        assert rebuild is not None
        fail_job(session, rebuild, "rebuild exploded", worker_id="meta-worker", max_attempts=1)
        session.commit()

    with Session() as session:
        request = session.get(SyncRequest, request_id)
        target = session.get(SyncRequestTarget, target_id)
        assert request is not None and request.state == "failed"
        assert target is not None and target.state == "failed"
