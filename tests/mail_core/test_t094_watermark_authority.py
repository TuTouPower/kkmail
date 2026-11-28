"""t094: authoritative delta watermark, queue retention and index contract.

Covers AC-001/002 (checkpoint-only scheduling + settlement classification),
AC-003 (retention eligibility / link re-aggregation safety), AC-004/005
(index contract) and AC-006/007 (stats threshold + backlog drain).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from mail_core.mail.domain.enums import ExecutionOrigin, FolderRemoteState, JobStatus, JobType
from mail_core.mail.storage.models import (
    Folder,
    SyncCheckpoint,
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.sync.checkpoints import advance_delta_settlement_watermark
from mail_core.sync.jobs import complete_job, fail_job, prune_completed_jobs
from mail_core.worker.main import schedule_periodic_inbox_sync

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_account_with_inbox(session, *, prefix: str = "t094"):
    from mail_core.mail.storage.models import Account

    acc = Account(
        id=uuid.uuid4(),
        email=f"{prefix}-{uuid.uuid4().hex[:6]}@example.com",
        provider="stub",
        credential_ref=f"ref-{uuid.uuid4().hex[:6]}",
        sync_enabled=True,
    )
    session.add(acc)
    session.flush()
    folder = Folder(
        id=uuid.uuid4(),
        account_id=acc.id,
        remote_id=f"remote-{uuid.uuid4().hex[:6]}",
        name="Inbox",
        role="inbox",
        remote_state=FolderRemoteState.ACTIVE.value,
    )
    session.add(folder)
    session.flush()
    return acc, folder


def test_ac001_checkpoint_watermark_is_authoritative_not_job_history():
    """The authoritative watermark is the checkpoint, not terminal job history.

    Discrimination: a fresh terminal job (10s ago) with a stale checkpoint
    watermark (1h ago) must schedule (checkpoint says overdue). The old dual-
    source ``max(cp.updated_at, latest_job_finished)`` would see the fresh job
    and skip — so this test fails on the old logic. The inverse case is kept
    as a complementary assertion.
    """
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session)
        stale = datetime.now(timezone.utc) - timedelta(hours=1)
        cp = SyncCheckpoint(
            account_id=acc.id,
            folder_id=folder.id,
            full_scan_complete=True,
            last_delta_settled_at=stale,
        )
        session.add(cp)
        # A fresh terminal job must NOT suppress a checkpoint-due folder.
        session.add(
            WorkerJob(
                id=uuid.uuid4(),
                account_id=acc.id,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                execution_origin=ExecutionOrigin.BACKGROUND.value,
                dedupe_key=f"delta:{acc.id}:{folder.id}",
                status=JobStatus.FAILED.value,
                updated_at=datetime.now(timezone.utc) - timedelta(seconds=10),
                payload={"folder_id": str(folder.id)},
            )
        )
        session.commit()
        acc_id, folder_id = acc.id, folder.id

    with Session() as session:
        assert schedule_periodic_inbox_sync(session, poll_interval_s=1200.0) >= 1

    # Complement: a fresh watermark with only stale job history stays quiet.
    with Session() as session:
        cp = session.get(SyncCheckpoint, {"account_id": acc_id, "folder_id": folder_id})
        cp.last_delta_settled_at = datetime.now(timezone.utc) - timedelta(seconds=10)
        session.commit()
    with Session() as session:
        assert schedule_periodic_inbox_sync(session, poll_interval_s=1200.0) == 0


def test_ac002_no_baseline_is_not_delta_eligible():
    """A folder without a completed baseline is not dispatched to delta.

    Baseline discovery is owned by the metadata chain; scheduling a delta here
    would spin on baseline_required with no settlement to record. A baseline-
    ready checkpoint with a NULL watermark is the "first pass due" state.
    """
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="nobase")
        session.commit()
        acc_id, folder_id = acc.id, folder.id

    with Session() as session:
        assert schedule_periodic_inbox_sync(session, poll_interval_s=1200.0) == 0
        assert (
            session.scalar(
                select(WorkerJob).where(WorkerJob.dedupe_key == f"delta:{acc_id}:{folder_id}")
            )
            is None
        )

    with Session() as session:
        session.add(
            SyncCheckpoint(
                account_id=acc_id,
                folder_id=folder_id,
                full_scan_complete=True,
                last_delta_settled_at=None,
            )
        )
        session.commit()
    with Session() as session:
        assert schedule_periodic_inbox_sync(session, poll_interval_s=1200.0) >= 1


def test_ac002_watermark_monotonic_and_backward_safe():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="mono")
        cp = SyncCheckpoint(
            account_id=acc.id,
            folder_id=folder.id,
            full_scan_complete=True,
            last_delta_settled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        session.add(cp)
        session.commit()
        acc_id, folder_id = acc.id, folder.id

    newer = datetime.now(timezone.utc)
    with Session() as session:
        assert advance_delta_settlement_watermark(
            session, account_id=acc_id, folder_id=folder_id, settled_at=newer
        )
        session.commit()
    with Session() as session:
        cp = session.get(SyncCheckpoint, {"account_id": acc_id, "folder_id": folder_id})
        assert cp.last_delta_settled_at >= newer
        # A superseded execution with an older settlement cannot move backwards.
        assert advance_delta_settlement_watermark(
            session,
            account_id=acc_id,
            folder_id=folder_id,
            settled_at=newer - timedelta(hours=1),
        ) is False


def _seed_terminal_job_with_target(session, *, target_state: str):
    acc, folder = _seed_account_with_inbox(session, prefix="reclaim")
    req = SyncRequest(
        id=uuid.uuid4(),
        client_request_id=f"req-{uuid.uuid4().hex[:8]}",
        mode="delta",
        trigger="manual",
        state="running" if target_state == "running" else "complete",
        scope={},
    )
    session.add(req)
    session.flush()
    target = SyncRequestTarget(
        id=uuid.uuid4(),
        request_id=req.id,
        account_id=acc.id,
        folder_id=folder.id,
        target_key=f"{acc.id}:{folder.id}",
        requested_generation=uuid.uuid4(),
        state=target_state,
    )
    session.add(target)
    session.flush()
    job = WorkerJob(
        id=uuid.uuid4(),
        account_id=acc.id,
        job_type=JobType.SYNC_FOLDER_DELTA.value,
        execution_origin=ExecutionOrigin.BACKGROUND.value,
        status=JobStatus.FAILED.value,
        updated_at=datetime.now(timezone.utc) - timedelta(days=2),
        payload={"folder_id": str(folder.id)},
    )
    session.add(job)
    session.flush()
    session.add(
        SyncRequestTargetJob(
            id=uuid.uuid4(),
            target_id=target.id,
            job_id=job.id,
            status="failed",
        )
    )
    session.flush()
    return job.id


def test_ac003_prune_keeps_terminal_job_linked_to_open_target():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        job_id = _seed_terminal_job_with_target(session, target_state="running")
        session.commit()

    with Session() as session:
        assert prune_completed_jobs(session) == 0
        assert session.get(WorkerJob, job_id) is not None


def test_ac003_prune_removes_terminal_job_linked_to_settled_target():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        job_id = _seed_terminal_job_with_target(session, target_state="complete")
        session.commit()

    with Session() as session:
        assert prune_completed_jobs(session) >= 1
        assert session.get(WorkerJob, job_id) is None


def test_ac005_prune_query_can_use_partial_index():
    """AC-005: cleanup uses the terminal partial index under a general plan.

    Representative data (bulk terminal rows + a few active rows) is seeded and
    ANALYZEd; EXPLAIN runs in the production bind-parameter shape with the
    default planner settings (no forced seqscan-off). The plan must use the
    partial index and avoid a heap Seq Scan.
    """
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="explain")
        old = datetime.now(timezone.utc) - timedelta(days=3)
        for _ in range(2000):
            session.add(
                WorkerJob(
                    id=uuid.uuid4(), account_id=acc.id,
                    job_type=JobType.SYNC_FOLDER_DELTA.value,
                    execution_origin=ExecutionOrigin.BACKGROUND.value,
                    status=JobStatus.DONE.value,
                    updated_at=old,
                    payload={"folder_id": str(folder.id)},
                )
            )
        for _ in range(20):
            session.add(
                WorkerJob(
                    id=uuid.uuid4(), account_id=acc.id,
                    job_type=JobType.SYNC_FOLDER_DELTA.value,
                    execution_origin=ExecutionOrigin.BACKGROUND.value,
                    status=JobStatus.PENDING.value,
                    payload={"folder_id": str(folder.id)},
                )
            )
        session.commit()
        session.execute(text("ANALYZE worker_jobs"))
        stmt = text(
            "EXPLAIN SELECT id FROM worker_jobs "
            "WHERE status IN ('done', 'failed') AND updated_at < :cutoff "
            "ORDER BY updated_at ASC LIMIT 1000"
        )
        rows = list(session.execute(stmt, {"cutoff": cutoff}).all())
        plan = "\n".join(str(row[0]) for row in rows)
        assert "ix_worker_jobs_terminal_cleanup" in plan
        assert "Seq Scan" not in plan


def test_ac002_complete_job_advances_watermark_for_settled_delta():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="settle")
        cp = SyncCheckpoint(
            account_id=acc.id,
            folder_id=folder.id,
            full_scan_complete=True,
            last_delta_settled_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        session.add(cp)
        session.flush()
        job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc.id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND.value,
            status=JobStatus.CLAIMED.value,
            locked_by="worker-1",
            payload={"folder_id": str(folder.id)},
        )
        session.add(job)
        session.commit()
        job_id = job.id
        acc_id, folder_id = acc.id, folder.id

    with Session() as session:
        job = session.get(WorkerJob, job_id)
        complete_job(session, job, worker_id="worker-1", result={"status": "ok", "exhausted": True})
        session.commit()

    with Session() as session:
        cp = session.get(SyncCheckpoint, {"account_id": acc_id, "folder_id": folder_id})
        assert cp.last_delta_settled_at is not None
        assert cp.last_delta_settled_at > datetime.now(timezone.utc) - timedelta(minutes=1)


def test_ac002_scan_generation_does_not_disable_periodic_delta():
    """A completed baseline keeps its scan_generation; it must stay eligible."""
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="genkept")
        session.add(
            SyncCheckpoint(
                account_id=acc.id,
                folder_id=folder.id,
                full_scan_complete=True,
                scan_generation=uuid.uuid4(),
                last_delta_settled_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )
        session.commit()
        acc_id, folder_id = acc.id, folder.id
    with Session() as session:
        assert schedule_periodic_inbox_sync(session, poll_interval_s=1200.0) >= 1


def test_ac002_fail_job_terminal_advances_watermark():
    """Retry-exhausted delta failure advances the watermark (settlement)."""
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="failterm")
        session.add(
            SyncCheckpoint(
                account_id=acc.id,
                folder_id=folder.id,
                full_scan_complete=True,
                last_delta_settled_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
        )
        session.flush()
        job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc.id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND.value,
            status=JobStatus.CLAIMED.value,
            locked_by="worker-fail",
            failure_attempts=7,
            payload={"folder_id": str(folder.id)},
        )
        session.add(job)
        session.commit()
        job_id = job.id
        acc_id, folder_id = acc.id, folder.id

    with Session() as session:
        job = session.get(WorkerJob, job_id)
        fail_job(session, job, "terminal failure", worker_id="worker-fail", max_attempts=8)
        assert job.status == JobStatus.FAILED.value
        session.commit()

    with Session() as session:
        cp = session.get(SyncCheckpoint, {"account_id": acc_id, "folder_id": folder_id})
        assert cp.last_delta_settled_at > datetime.now(timezone.utc) - timedelta(minutes=1)


def test_ac002_fencing_token_rejects_stale_execution():
    """A delta execution older than the checkpoint's token cannot advance."""
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="fence")
        old = datetime.now(timezone.utc) - timedelta(hours=1)
        session.add(
            SyncCheckpoint(
                account_id=acc.id,
                folder_id=folder.id,
                full_scan_complete=True,
                fencing_token=10,
                last_delta_settled_at=old,
            )
        )
        session.commit()
        acc_id, folder_id = acc.id, folder.id

    with Session() as session:
        # Stale token 5 < checkpoint token 10: rejected even with a fresh time.
        assert advance_delta_settlement_watermark(
            session,
            account_id=acc_id,
            folder_id=folder_id,
            settled_at=datetime.now(timezone.utc),
            fencing_token=5,
        ) is False
        # Current token 10: accepted.
        assert advance_delta_settlement_watermark(
            session,
            account_id=acc_id,
            folder_id=folder_id,
            settled_at=datetime.now(timezone.utc),
            fencing_token=10,
        ) is True


def test_ac003_reclaim_preserves_failed_branch_for_running_sibling():
    """A failed link is not recycled while a sibling target link is still open."""
    from mail_core.db.session import get_session_factory
    from mail_core.sync.execution import refresh_requests

    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="twobranch")
        req = SyncRequest(
            id=uuid.uuid4(),
            client_request_id=f"req-two-{uuid.uuid4().hex[:8]}",
            mode="delta",
            trigger="manual",
            state="running",
            scope={},
        )
        session.add(req)
        session.flush()
        target = SyncRequestTarget(
            id=uuid.uuid4(),
            request_id=req.id,
            account_id=acc.id,
            folder_id=folder.id,
            target_key=f"{acc.id}:{folder.id}",
            requested_generation=uuid.uuid4(),
            state="running",
        )
        session.add(target)
        session.flush()
        failed_job = WorkerJob(
            id=uuid.uuid4(), account_id=acc.id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND.value,
            status=JobStatus.FAILED.value,
            updated_at=datetime.now(timezone.utc) - timedelta(days=2),
            payload={"folder_id": str(folder.id)},
        )
        running_job = WorkerJob(
            id=uuid.uuid4(), account_id=acc.id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND.value,
            status=JobStatus.CLAIMED.value,
            locked_by="w",
            payload={"folder_id": str(folder.id)},
        )
        session.add_all([failed_job, running_job])
        session.flush()
        session.add(SyncRequestTargetJob(id=uuid.uuid4(), target_id=target.id, job_id=failed_job.id, status="failed", error_code="job_failed"))
        session.add(SyncRequestTargetJob(id=uuid.uuid4(), target_id=target.id, job_id=running_job.id, status="running"))
        session.commit()
        failed_id, running_id = failed_job.id, running_job.id
        req_id, target_id = req.id, target.id

    with Session() as session:
        assert prune_completed_jobs(session) == 0
        assert session.get(WorkerJob, failed_id) is not None

    # Complete the slow sibling; the request must stay failed with its error.
    with Session() as session:
        j = session.get(WorkerJob, running_id)
        j.status = JobStatus.DONE.value
        j.locked_by = None
        from mail_core.sync.execution import settle_job_links

        settle_job_links(session, j, outcome="complete", result={"status": "ok"})
        refresh_requests(session, {req_id})
        session.commit()
    with Session() as session:
        req = session.get(SyncRequest, req_id)
        assert req.state == "failed"


def test_ac007_backlog_drains_respecting_batch_cap():
    """A backlog larger than the cap drains in bounded batches to steady state."""
    from mail_core.db.session import get_session_factory
    from mail_core.sync.retention import COMPLETED_JOB_PRUNE_BATCH

    Session = get_session_factory()
    n = COMPLETED_JOB_PRUNE_BATCH + 25
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="backlog")
        old = datetime.now(timezone.utc) - timedelta(days=2)
        for _ in range(n):
            session.add(
                WorkerJob(
                    id=uuid.uuid4(), account_id=acc.id,
                    job_type=JobType.SYNC_FOLDER_DELTA.value,
                    execution_origin=ExecutionOrigin.BACKGROUND.value,
                    status=JobStatus.DONE.value,
                    updated_at=old,
                    payload={"folder_id": str(folder.id)},
                )
            )
        session.commit()

    total = 0
    for _ in range(10):
        with Session() as session:
            deleted = prune_completed_jobs(session)
            assert deleted <= COMPLETED_JOB_PRUNE_BATCH
            session.commit()
        total += deleted
        if deleted == 0:
            break
    assert total == n


def test_ac002_rebuilding_folder_not_delta_eligible():
    """A folder whose baseline is being rebuilt (full_scan_complete=False) is
    not dispatched to delta — the metadata chain owns the rebuild."""
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="rebuild")
        session.add(
            SyncCheckpoint(
                account_id=acc.id,
                folder_id=folder.id,
                full_scan_complete=False,
                scan_generation=uuid.uuid4(),
                last_delta_settled_at=None,
            )
        )
        session.commit()
        acc_id, folder_id = acc.id, folder.id
    with Session() as session:
        assert schedule_periodic_inbox_sync(session, poll_interval_s=1200.0) == 0
