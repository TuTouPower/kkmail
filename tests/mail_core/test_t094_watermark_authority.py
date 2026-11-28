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


def test_ac003_prune_protects_failed_target_while_parent_request_open():
    """Finding 1: a two-target request with A failed (>24h) and B open must
    never prune A's jobs while parent SyncRequest is open, and settling B
    must keep A failed and the parent request failed.
    """
    from mail_core.db.session import get_session_factory
    from mail_core.sync.execution import refresh_requests

    Session = get_session_factory()
    old = datetime.now(timezone.utc) - timedelta(days=2)
    with Session() as session:
        acc, folder_a = _seed_account_with_inbox(session, prefix="f1a")
        folder_b = Folder(
            id=uuid.uuid4(),
            account_id=acc.id,
            remote_id=f"sent-{uuid.uuid4().hex[:6]}",
            name="Sent",
            role="sent",
            remote_state=FolderRemoteState.ACTIVE.value,
        )
        session.add(folder_b)
        session.flush()

        req = SyncRequest(
            id=uuid.uuid4(),
            client_request_id=f"req-f1-{uuid.uuid4().hex[:8]}",
            mode="delta",
            trigger="manual",
            state="running",
            scope={},
        )
        session.add(req)
        session.flush()

        target_a = SyncRequestTarget(
            id=uuid.uuid4(),
            request_id=req.id,
            account_id=acc.id,
            folder_id=folder_a.id,
            target_key=f"a:{folder_a.id}",
            requested_generation=uuid.uuid4(),
            state="failed",
            error_code="job_failed",
            safe_error="upstream failed",
            finished_at=old,
        )
        target_b = SyncRequestTarget(
            id=uuid.uuid4(),
            request_id=req.id,
            account_id=acc.id,
            folder_id=folder_b.id,
            target_key=f"b:{folder_b.id}",
            requested_generation=uuid.uuid4(),
            state="running",
        )
        session.add_all([target_a, target_b])
        session.flush()

        failed_job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc.id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.FOREGROUND.value,
            status=JobStatus.FAILED.value,
            updated_at=old,
            payload={"folder_id": str(folder_a.id)},
        )
        done_job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc.id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.FOREGROUND.value,
            status=JobStatus.DONE.value,
            updated_at=datetime.now(timezone.utc),
            payload={"folder_id": str(folder_a.id)},
        )
        claimed_job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc.id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.FOREGROUND.value,
            status=JobStatus.CLAIMED.value,
            locked_by="w-f1",
            payload={"folder_id": str(folder_b.id)},
        )
        session.add_all([failed_job, done_job, claimed_job])
        session.flush()
        session.add_all(
            [
                SyncRequestTargetJob(
                    id=uuid.uuid4(),
                    target_id=target_a.id,
                    job_id=failed_job.id,
                    status="failed",
                    error_code="job_failed",
                    safe_error="upstream failed",
                ),
                SyncRequestTargetJob(
                    id=uuid.uuid4(),
                    target_id=target_a.id,
                    job_id=done_job.id,
                    status="complete",
                ),
                SyncRequestTargetJob(
                    id=uuid.uuid4(),
                    target_id=target_b.id,
                    job_id=claimed_job.id,
                    status="running",
                ),
            ]
        )
        session.commit()
        req_id = req.id
        target_a_id, target_b_id = target_a.id, target_b.id
        failed_job_id, claimed_job_id = failed_job.id, claimed_job.id

    with Session() as session:
        assert prune_completed_jobs(session) == 0
        assert session.get(WorkerJob, failed_job_id) is not None

    with Session() as session:
        complete_job(
            session,
            session.get(WorkerJob, claimed_job_id),
            worker_id="w-f1",
            result={"status": "ok", "exhausted": True},
        )
        session.commit()

    with Session() as session:
        req = session.get(SyncRequest, req_id)
        ta = session.get(SyncRequestTarget, target_a_id)
        tb = session.get(SyncRequestTarget, target_b_id)
        assert ta.state == "failed"
        assert ta.error_code == "job_failed"
        assert ta.safe_error == "upstream failed"
        assert tb.state == "complete"
        assert req.state == "failed"

    # Once the parent request is terminal, old failed jobs become prunable, and
    # a subsequent refresh must still preserve A's terminal failure state.
    with Session() as session:
        assert prune_completed_jobs(session) == 1
        assert session.get(WorkerJob, failed_job_id) is None
        refresh_requests(session, {req_id})
        session.commit()

    with Session() as session:
        req = session.get(SyncRequest, req_id)
        ta = session.get(SyncRequestTarget, target_a_id)
        assert ta.state == "failed"
        assert ta.error_code == "job_failed"
        assert ta.safe_error == "upstream failed"
        assert req.state == "failed"


def test_ac003_refresh_requests_preserves_terminal_targets_and_allows_retry_reopen():
    """Terminal target states without open links must not be overwritten by
    link pruning/changes, while binding an open retry link re-opens the target.
    """
    from mail_core.db.session import get_session_factory
    from mail_core.sync.execution import bind_target, refresh_requests

    Session = get_session_factory()
    old = datetime.now(timezone.utc) - timedelta(days=2)
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="termkeep")
        req = SyncRequest(
            id=uuid.uuid4(),
            client_request_id=f"req-term-{uuid.uuid4().hex[:8]}",
            mode="delta",
            trigger="manual",
            state="running",
            scope={},
        )
        session.add(req)
        session.flush()

        preserved_targets = []
        for idx, state in enumerate(("complete", "partial", "failed", "cancelled", "blocked")):
            t = SyncRequestTarget(
                id=uuid.uuid4(),
                request_id=req.id,
                account_id=acc.id,
                folder_id=folder.id,
                target_key=f"t:{idx}:{state}",
                requested_generation=uuid.uuid4(),
                state=state,
                error_code=None if state == "complete" else f"err_{state}",
                safe_error=None if state == "complete" else f"msg_{state}",
                finished_at=old,
            )
            session.add(t)
            session.flush()
            done_job = WorkerJob(
                id=uuid.uuid4(),
                account_id=acc.id,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                execution_origin=ExecutionOrigin.FOREGROUND.value,
                status=JobStatus.DONE.value,
                payload={"folder_id": str(folder.id)},
            )
            session.add(done_job)
            session.flush()
            session.add(
                SyncRequestTargetJob(
                    id=uuid.uuid4(),
                    target_id=t.id,
                    job_id=done_job.id,
                    status="complete",
                )
            )
            preserved_targets.append((t.id, state))
        session.commit()
        req_id = req.id

    with Session() as session:
        refresh_requests(session, {req_id})
        session.commit()

    with Session() as session:
        req = session.get(SyncRequest, req_id)
        assert req.state == "failed"
        for tid, state in preserved_targets:
            t = session.get(SyncRequestTarget, tid)
            assert t.state == state
            assert t.finished_at == old
            if state != "complete":
                assert t.error_code == f"err_{state}"
                assert t.safe_error == f"msg_{state}"

    # Retry flow: a standalone failed target re-opened by bind_target with an
    # open job must re-enter queued/running and then settle complete.
    with Session() as session:
        acc2, folder2 = _seed_account_with_inbox(session, prefix="retryflow")
        req2 = SyncRequest(
            id=uuid.uuid4(),
            client_request_id=f"req-retry-{uuid.uuid4().hex[:8]}",
            mode="delta",
            trigger="manual",
            state="failed",
            scope={},
            finished_at=old,
        )
        session.add(req2)
        session.flush()
        t_retry = SyncRequestTarget(
            id=uuid.uuid4(),
            request_id=req2.id,
            account_id=acc2.id,
            folder_id=folder2.id,
            target_key=f"retry:{folder2.id}",
            requested_generation=uuid.uuid4(),
            state="failed",
            error_code="job_failed",
            safe_error="old failure",
            finished_at=old,
        )
        retry_job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc2.id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.FOREGROUND.value,
            status=JobStatus.PENDING.value,
            payload={"folder_id": str(folder2.id)},
        )
        session.add_all([t_retry, retry_job])
        session.flush()
        bind_target(session, target=t_retry, job=retry_job, status="queued")
        refresh_requests(session, {req2.id})
        session.commit()
        acc2_id = acc2.id
        req2_id, t_retry_id, retry_job_id = req2.id, t_retry.id, retry_job.id

    with Session() as session:
        assert session.get(SyncRequestTarget, t_retry_id).state in ("queued", "running")
        assert session.get(SyncRequest, req2_id).state in ("queued", "running")
        from mail_core.sync.jobs import claim_jobs

        claimed = claim_jobs(
            session,
            worker_id="w-retry",
            limit=1,
            account_id=acc2_id,
            job_types=[JobType.SYNC_FOLDER_DELTA.value],
        )
        assert [j.id for j in claimed] == [retry_job_id]
        complete_job(
            session,
            claimed[0],
            worker_id="w-retry",
            result={"status": "ok", "exhausted": True},
        )
        session.commit()

    with Session() as session:
        assert session.get(SyncRequestTarget, t_retry_id).state == "complete"
        assert session.get(SyncRequestTarget, t_retry_id).error_code is None
        assert session.get(SyncRequest, req2_id).state == "complete"


def _sql_literal_for_execute(value):
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, datetime):
        return f"'{value.isoformat()}'::timestamptz"
    if isinstance(value, uuid.UUID):
        return f"'{value}'::uuid"
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def test_ac005_production_orm_queries_use_partial_indexes_under_force_generic_plan():
    """Finding 6: real ORM SQL from prune_completed_jobs, enqueue_job,
    find_active_job, and _inflight_full_root_generation must hit the partial
    indexes (and avoid Seq Scan on sync_request_targets) under force_generic_plan.
    """
    from sqlalchemy import event
    from sqlalchemy.dialects import postgresql

    from mail_core.db.session import get_session_factory
    from mail_core.mail.application.sync_requests import _inflight_full_root_generation
    from mail_core.sync.execution import find_active_job
    from mail_core.sync.jobs import enqueue_job

    Session = get_session_factory()

    class _Captured(Exception):
        pass

    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="gplan")
        acc_id = acc.id
        session.add(
            SyncCheckpoint(
                account_id=acc.id,
                folder_id=folder.id,
                full_scan_complete=True,
                last_delta_settled_at=datetime.now(timezone.utc) - timedelta(hours=1),
            )
        )
        session.flush()
        session.execute(
            text(
                """
                INSERT INTO worker_jobs (id, job_type, execution_origin, status, updated_at, dedupe_key)
                SELECT gen_random_uuid(), 'sync_folder_delta', 'background',
                       CASE WHEN n <= 10000 THEN 'done'
                            WHEN n <= 20000 THEN 'failed'
                            WHEN n <= 20020 THEN 'pending'
                            ELSE 'claimed' END,
                       now() - interval '3 days',
                       'gplan:' || n
                FROM generate_series(1, 20040) AS n
                """
            )
        )
        # Seed 5,000 settled requests + targets + links so the anti-join planner
        # chooses index lookups over sync_request_targets instead of Seq Scan.
        session.execute(
            text(
                """
                WITH reqs AS (
                    INSERT INTO sync_requests (id, client_request_id, mode, trigger, state, scope)
                    SELECT gen_random_uuid(), 'gp-req-' || n, 'delta', 'manual', 'complete', '{}'::jsonb
                    FROM generate_series(1, 5000) AS n
                    RETURNING id, client_request_id
                ),
                tgs AS (
                    INSERT INTO sync_request_targets (id, request_id, target_key, requested_generation, state)
                    SELECT gen_random_uuid(), reqs.id, 'k:' || reqs.client_request_id, gen_random_uuid(), 'complete'
                    FROM reqs
                    RETURNING id
                ),
                sample_jobs AS (
                    SELECT id, row_number() OVER () AS rn
                    FROM worker_jobs
                    WHERE status IN ('done', 'failed')
                    LIMIT 5000
                ),
                numbered_tgs AS (
                    SELECT id, row_number() OVER () AS rn
                    FROM tgs
                )
                INSERT INTO sync_request_target_jobs (id, target_id, job_id, status)
                SELECT gen_random_uuid(), numbered_tgs.id, sample_jobs.id, 'complete'
                FROM numbered_tgs
                JOIN sample_jobs ON sample_jobs.rn = numbered_tgs.rn
                """
            )
        )
        session.execute(text("ANALYZE worker_jobs"))
        session.execute(text("ANALYZE sync_requests"))
        session.execute(text("ANALYZE sync_request_targets"))
        session.execute(text("ANALYZE sync_request_target_jobs"))

        captured: dict[str, object] = {}
        current_label = {"name": ""}

        def _capture(orm_state):
            if current_label["name"] == "inbox_dedupe" and "worker_jobs" not in str(orm_state.statement):
                return
            captured[current_label["name"]] = orm_state.statement
            raise _Captured

        event.listen(session, "do_orm_execute", _capture)
        try:
            operations = [
                ("prune", lambda: prune_completed_jobs(session)),
                (
                    "enqueue_dedupe",
                    lambda: enqueue_job(
                        session,
                        job_type=JobType.SYNC_FOLDER_DELTA.value,
                        execution_origin=ExecutionOrigin.BACKGROUND,
                        dedupe_key="gplan:20020",
                    ),
                ),
                ("find_active", lambda: find_active_job(session, "gplan:20020")),
                ("inflight_sync", lambda: _inflight_full_root_generation(session, acc_id)),
                ("inbox_dedupe", lambda: schedule_periodic_inbox_sync(session, idle_held_account_ids=set())),
            ]
            for label, fn in operations:
                current_label["name"] = label
                try:
                    fn()
                except _Captured:
                    pass
        finally:
            event.remove(session, "do_orm_execute", _capture)

        assert set(captured) == {"prune", "enqueue_dedupe", "find_active", "inflight_sync", "inbox_dedupe"}

        conn = session.connection()
        conn.exec_driver_sql("SET LOCAL plan_cache_mode = 'force_generic_plan'")
        plans: dict[str, str] = {}
        for idx, (label, stmt) in enumerate(captured.items()):
            compiled = stmt.compile(
                dialect=postgresql.dialect(paramstyle="numeric_dollar"),
                compile_kwargs={"render_postcompile": True},
            )
            args = [_sql_literal_for_execute(compiled.params[p]) for p in (compiled.positiontup or ())]
            prep_name = f"t094_gp_{idx}"
            conn.exec_driver_sql(f"PREPARE {prep_name} AS {compiled.string}")
            exec_sql = (
                f"EXPLAIN (COSTS OFF) EXECUTE {prep_name}({', '.join(args)})"
                if args
                else f"EXPLAIN (COSTS OFF) EXECUTE {prep_name}"
            )
            plans[label] = "\n".join(row[0] for row in conn.exec_driver_sql(exec_sql))
            conn.exec_driver_sql(f"DEALLOCATE {prep_name}")

        assert "ix_worker_jobs_terminal_cleanup" in plans["prune"], plans["prune"]
        assert "ix_worker_jobs_claim" not in plans["prune"], plans["prune"]
        assert "Sort" not in plans["prune"], plans["prune"]
        assert "Seq Scan" not in plans["prune"], plans["prune"]

        for active_label in ("enqueue_dedupe", "find_active", "inflight_sync", "inbox_dedupe"):
            assert "ix_worker_jobs_dedupe_active" in plans[active_label], plans[active_label]
            assert "ix_worker_jobs_claim" not in plans[active_label], plans[active_label]
            assert "Seq Scan" not in plans[active_label], plans[active_label]

        session.rollback()


def test_ac007_prune_completed_jobs_enforces_limit_bounds():
    """AC-007: limit <= 0 returns 0 and oversized limits are capped at COMPLETED_JOB_PRUNE_BATCH."""
    from mail_core.db.session import get_session_factory
    from mail_core.sync.retention import COMPLETED_JOB_PRUNE_BATCH

    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        session.execute(
            text(
                """
                INSERT INTO worker_jobs (id, job_type, execution_origin, status, updated_at)
                SELECT gen_random_uuid(), 'sync_folder_delta', 'background', 'done',
                       :now - interval '48 hours' - (n || ' milliseconds')::interval
                FROM generate_series(1, :total) AS n
                """
            ),
            {"now": now, "total": COMPLETED_JOB_PRUNE_BATCH + 50},
        )
        session.commit()

    with Session() as session:
        assert prune_completed_jobs(session, now=now, limit=0) == 0
        assert prune_completed_jobs(session, now=now, limit=-5) == 0
        deleted = prune_completed_jobs(
            session, now=now, limit=COMPLETED_JOB_PRUNE_BATCH * 4
        )
        assert deleted == COMPLETED_JOB_PRUNE_BATCH
        session.commit()

    with Session() as session:
        remaining = session.scalar(text("SELECT count(*) FROM worker_jobs"))
        assert remaining == 50


def test_ac007_steady_state_drain_80k_jobs_and_86k_outbox_preserves_fresh():
    """AC-007: drain 80k expired worker_jobs + 86k expired outbox rows across
    bounded 5,000-row sweeps to zero expired rows while preserving <24h rows.
    """
    from mail_core.db.session import get_session_factory
    from mail_core.realtime.outbox import prune_published, pruned_through_seq
    from mail_core.realtime.publication import get_publication_state
    from mail_core.sync.retention import (
        COMPLETED_JOB_PRUNE_BATCH,
        PUBLISHED_OUTBOX_PRUNE_BATCH,
    )

    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    expired_jobs_n = 80_000
    fresh_terminal_jobs_n = 80
    active_jobs_n = 40
    expired_outbox_n = 86_000
    fresh_outbox_n = 150
    unpublished_outbox_n = 25

    with Session() as session:
        session.execute(
            text(
                """
                INSERT INTO worker_jobs (id, job_type, execution_origin, status, updated_at)
                SELECT gen_random_uuid(), 'sync_folder_delta', 'background',
                       CASE WHEN n % 2 = 0 THEN 'done' ELSE 'failed' END,
                       :now - interval '25 hours' - (n || ' milliseconds')::interval
                FROM generate_series(1, :expired_jobs_n) AS n
                """
            ),
            {"now": now, "expired_jobs_n": expired_jobs_n},
        )
        session.execute(
            text(
                """
                INSERT INTO worker_jobs (id, job_type, execution_origin, status, updated_at)
                SELECT gen_random_uuid(), 'sync_folder_delta', 'background',
                       CASE WHEN n <= :fresh_terminal_jobs_n THEN 'done' ELSE 'pending' END,
                       :now - interval '1 hour'
                FROM generate_series(1, :fresh_total) AS n
                """
            ),
            {
                "now": now,
                "fresh_terminal_jobs_n": fresh_terminal_jobs_n,
                "fresh_total": fresh_terminal_jobs_n + active_jobs_n,
            },
        )

        pub_state = get_publication_state(session, with_for_update=True)
        base_seq = int(pub_state.next_seq)
        session.execute(
            text(
                """
                INSERT INTO outbox (event_type, payload, created_at, publication_seq, published_at)
                SELECT 'sync.progress', '{}'::jsonb,
                       :now - interval '26 hours',
                       :base_seq + n - 1,
                       :now - interval '25 hours'
                FROM generate_series(1, :expired_outbox_n) AS n
                """
            ),
            {"now": now, "base_seq": base_seq, "expired_outbox_n": expired_outbox_n},
        )
        session.execute(
            text(
                """
                INSERT INTO outbox (event_type, payload, created_at, publication_seq, published_at)
                SELECT 'sync.progress', '{}'::jsonb,
                       :now - interval '2 hours',
                       :fresh_base + n - 1,
                       :now - interval '1 hour'
                FROM generate_series(1, :fresh_outbox_n) AS n
                """
            ),
            {
                "now": now,
                "fresh_base": base_seq + expired_outbox_n,
                "fresh_outbox_n": fresh_outbox_n,
            },
        )
        session.execute(
            text(
                """
                INSERT INTO outbox (event_type, payload, created_at)
                SELECT 'sync.progress', '{}'::jsonb, :now - interval '48 hours'
                FROM generate_series(1, :unpublished_outbox_n) AS n
                """
            ),
            {"now": now, "unpublished_outbox_n": unpublished_outbox_n},
        )
        pub_state.next_seq = base_seq + expired_outbox_n + fresh_outbox_n
        session.commit()

    jobs_deleted_total = 0
    job_sweeps = 0
    while True:
        with Session() as session:
            deleted = prune_completed_jobs(session, now=now)
            assert deleted <= COMPLETED_JOB_PRUNE_BATCH
            session.commit()
        jobs_deleted_total += deleted
        if deleted == 0:
            break
        job_sweeps += 1
        assert job_sweeps <= 25

    outbox_deleted_total = 0
    outbox_sweeps = 0
    while True:
        with Session() as session:
            deleted = prune_published(session, now=now)
            assert deleted <= PUBLISHED_OUTBOX_PRUNE_BATCH
            session.commit()
        outbox_deleted_total += deleted
        if deleted == 0:
            break
        outbox_sweeps += 1
        assert outbox_sweeps <= 25

    assert jobs_deleted_total == expired_jobs_n
    assert outbox_deleted_total == expired_outbox_n

    cutoff = now - timedelta(hours=24)
    with Session() as session:
        expired_jobs_left = session.scalar(
            text(
                "SELECT count(*) FROM worker_jobs "
                "WHERE status IN ('done', 'failed') AND updated_at < :cutoff"
            ),
            {"cutoff": cutoff},
        )
        total_jobs_left = session.scalar(text("SELECT count(*) FROM worker_jobs"))
        expired_outbox_left = session.scalar(
            text(
                "SELECT count(*) FROM outbox "
                "WHERE publication_seq IS NOT NULL AND published_at < :cutoff"
            ),
            {"cutoff": cutoff},
        )
        total_outbox_left = session.scalar(text("SELECT count(*) FROM outbox"))
        assert expired_jobs_left == 0
        assert total_jobs_left == fresh_terminal_jobs_n + active_jobs_n
        assert expired_outbox_left == 0
        assert total_outbox_left == fresh_outbox_n + unpublished_outbox_n
        assert pruned_through_seq(session) == base_seq + expired_outbox_n - 1


def test_ac002_watermark_dual_tx_race_with_stale_orm_cannot_regress():
    """Finding 2: concurrent dual-TX race with stale ORM snapshot cannot regress
    watermark or fencing_token, and expires cached SyncCheckpoint in caller's session.
    Also verifies fencing_token=0 vs None semantics.
    """
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    t_base = datetime(2026, 11, 28, 1, 0, tzinfo=timezone.utc)
    t_newer = t_base + timedelta(minutes=1)
    t_later = t_base + timedelta(minutes=2)

    with Session() as session:
        acc, folder = _seed_account_with_inbox(session, prefix="race")
        session.add(
            SyncCheckpoint(
                account_id=acc.id,
                folder_id=folder.id,
                full_scan_complete=True,
                fencing_token=1,
            )
        )
        session.commit()
        key = {"account_id": acc.id, "folder_id": folder.id}

    with Session() as stale, Session() as current:
        cached = stale.get(SyncCheckpoint, key)
        assert cached is not None
        assert cached.fencing_token == 1

        new_cp = current.get(SyncCheckpoint, key)
        assert new_cp is not None
        new_cp.fencing_token = 2
        assert advance_delta_settlement_watermark(
            current, **key, fencing_token=2, settled_at=t_newer
        ) is True
        current.commit()

        # Stale session still sees cached fencing_token=1 until SQL UPDATE runs,
        # but the atomic conditional UPDATE must reject both older and newer times.
        assert cached.fencing_token == 1
        assert (
            advance_delta_settlement_watermark(
                stale, **key, fencing_token=1, settled_at=t_base
            )
            is False
        )
        assert (
            advance_delta_settlement_watermark(
                stale, **key, fencing_token=1, settled_at=t_later
            )
            is False
        )
        # Cached ORM instance must be expired so callers read fresh DB state.
        assert cached.fencing_token == 2
        assert cached.last_delta_settled_at == t_newer
        stale.commit()

    # Check fencing_token=0 vs None semantics on a fresh checkpoint (default token=0).
    with Session() as session:
        acc0, folder0 = _seed_account_with_inbox(session, prefix="tok0")
        session.add(
            SyncCheckpoint(
                account_id=acc0.id,
                folder_id=folder0.id,
                full_scan_complete=True,
                fencing_token=0,
            )
        )
        session.commit()
        k0 = {"account_id": acc0.id, "folder_id": folder0.id}

    with Session() as session:
        # token=0 matches checkpoint fencing_token=0
        assert (
            advance_delta_settlement_watermark(
                session, **k0, fencing_token=0, settled_at=t_base
            )
            is True
        )
        # Bump checkpoint token to 1; token=0 must now be rejected, while None skips token check.
        cp0 = session.get(SyncCheckpoint, k0)
        cp0.fencing_token = 1
        session.commit()

        assert (
            advance_delta_settlement_watermark(
                session, **k0, fencing_token=0, settled_at=t_newer
            )
            is False
        )
        assert (
            advance_delta_settlement_watermark(
                session, **k0, fencing_token=None, settled_at=t_newer
            )
            is True
        )
        session.commit()


def test_ac002_fail_reclaim_provider_error_carry_fencing_token_and_cannot_regress(
    monkeypatch,
):
    """Finding 2: provider_error, fail_job, and reclaim_stale_claims propagate true
    fencing_token so stale executions cannot regress a newer watermark.
    """
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import AccountSyncLease
    from mail_core.sync import delta as delta_mod
    from mail_core.sync.jobs import claim_jobs, enqueue_job, reclaim_stale_claims
    from mail_core.sync.leases import acquire_lease
    from mail_core.worker.handlers import handle_job

    Session = get_session_factory()
    t_old = datetime(2026, 11, 28, 1, 0, tzinfo=timezone.utc)
    t_newer = datetime(2026, 11, 28, 1, 1, tzinfo=timezone.utc)

    # Part A: provider_error via handle_job on terminal attempt propagates true token
    with Session() as session:
        acc_a, folder_a = _seed_account_with_inbox(session, prefix="prov-err")
        session.add(
            SyncCheckpoint(
                account_id=acc_a.id,
                folder_id=folder_a.id,
                full_scan_complete=True,
                fencing_token=0,
                last_delta_settled_at=t_old,
            )
        )
        job_a = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND,
            account_id=acc_a.id,
            payload={"folder_id": str(folder_a.id)},
            dedupe_key=f"delta:{acc_a.id}:{folder_a.id}",
        )
        job_a.failure_attempts = 7
        session.commit()
        acc_a_id, folder_a_id, job_a_id = acc_a.id, folder_a.id, job_a.id

    with Session() as session:
        claimed = claim_jobs(session, worker_id="w-prov", limit=1, account_id=acc_a_id)
        assert [j.id for j in claimed] == [job_a_id]
        session.commit()

    # Provider stalls on token=1 while a concurrent token=2 finishes with t_newer,
    # then provider raises -> terminal provider_error must NOT regress t_newer!
    class _StallThenFailProvider:
        def delta_changes(self, _rid, _cur):
            with Session() as s2:
                lease_row = s2.get(AccountSyncLease, acc_a_id)
                assert lease_row is not None
                assert lease_row.fencing_token == 1
                lease_row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=5)
                s2.commit()
            with Session() as s2:
                l2 = acquire_lease(s2, account_id=acc_a_id, owner_id="w-winner", ttl=timedelta(minutes=5))
                cp2 = s2.get(SyncCheckpoint, {"account_id": acc_a_id, "folder_id": folder_a_id})
                cp2.fencing_token = l2.fencing_token
                assert advance_delta_settlement_watermark(
                    s2,
                    account_id=acc_a_id,
                    folder_id=folder_a_id,
                    settled_at=t_newer,
                    fencing_token=l2.fencing_token,
                )
                s2.commit()
            raise TimeoutError("stale worker timed out")

    monkeypatch.setattr(delta_mod, "build_provider", lambda *_a, **_k: _StallThenFailProvider())
    monkeypatch.setattr("mail_core.worker.handlers.get_credential_store", lambda: object())

    with Session() as session:
        job = session.get(WorkerJob, job_a_id)
        assert handle_job(session, job, worker_id="w-prov") is False
        session.commit()

    with Session() as session:
        job = session.get(WorkerJob, job_a_id)
        cp = session.get(SyncCheckpoint, {"account_id": acc_a_id, "folder_id": folder_a_id})
        assert job.status == JobStatus.FAILED.value
        assert job.payload.get("_fencing_token") == 1
        assert cp.fencing_token == 2
        assert cp.last_delta_settled_at == t_newer

    # Part B: reclaim_stale_claims reads persisted _fencing_token on crash loop
    with Session() as session:
        acc_b, folder_b = _seed_account_with_inbox(session, prefix="reclaim-tok")
        session.add(
            SyncCheckpoint(
                account_id=acc_b.id,
                folder_id=folder_b.id,
                full_scan_complete=True,
                fencing_token=5,
                last_delta_settled_at=t_old,
            )
        )
        stale_job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc_b.id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND.value,
            status=JobStatus.CLAIMED.value,
            locked_by="w-crashed",
            locked_at=t_newer - timedelta(hours=1),
            failure_attempts=7,
            payload={"folder_id": str(folder_b.id), "_fencing_token": 3},
        )
        session.add(stale_job)
        session.commit()
        acc_b_id, folder_b_id, stale_job_id = acc_b.id, folder_b.id, stale_job.id

    with Session() as session:
        # Even with a later wall-clock `now`, stale _fencing_token=3 < cp.fencing_token=5 must not advance!
        assert (
            reclaim_stale_claims(
                session,
                older_than=timedelta(minutes=5),
                now=t_newer + timedelta(hours=1),
                max_attempts=8,
            )
            >= 1
        )
        session.commit()

    with Session() as session:
        cp_b = session.get(SyncCheckpoint, {"account_id": acc_b_id, "folder_id": folder_b_id})
        assert session.get(WorkerJob, stale_job_id).status == JobStatus.FAILED.value
        assert cp_b.last_delta_settled_at == t_old

    # Non-terminal reclaim clears _fencing_token before retry; terminal reclaim with current token=5 advances.
    with Session() as session:
        retriable_reclaim_job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc_b_id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND.value,
            status=JobStatus.CLAIMED.value,
            locked_by="w-crashed-retry",
            locked_at=t_newer - timedelta(hours=2),
            failure_attempts=0,
            payload={"folder_id": str(folder_b_id), "_fencing_token": 5},
        )
        session.add(retriable_reclaim_job)
        session.commit()
        retriable_reclaim_id = retriable_reclaim_job.id

    with Session() as session:
        assert (
            reclaim_stale_claims(
                session,
                older_than=timedelta(minutes=5),
                now=t_newer - timedelta(minutes=30),
                max_attempts=8,
            )
            >= 1
        )
        session.commit()

    with Session() as session:
        requeued = session.get(WorkerJob, retriable_reclaim_id)
        assert requeued.status == JobStatus.PENDING.value
        assert "_fencing_token" not in requeued.payload

    # Current _fencing_token=5 on terminal reclaim DOES advance watermark.
    with Session() as session:
        current_reclaim_job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc_b_id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND.value,
            status=JobStatus.CLAIMED.value,
            locked_by="w-crashed-cur",
            locked_at=t_newer - timedelta(hours=1),
            failure_attempts=7,
            payload={"folder_id": str(folder_b_id), "_fencing_token": 5},
        )
        session.add(current_reclaim_job)
        session.commit()

    with Session() as session:
        assert (
            reclaim_stale_claims(
                session,
                older_than=timedelta(minutes=5),
                now=t_newer,
                max_attempts=8,
            )
            >= 1
        )
        session.commit()

    with Session() as session:
        cp_b = session.get(SyncCheckpoint, {"account_id": acc_b_id, "folder_id": folder_b_id})
        assert cp_b.last_delta_settled_at == t_newer

    # Part C: terminal fail_job directly with stale _fencing_token cannot regress,
    # and a terminal provider_error winner (without apply_delta_page) blocks an older token.
    with Session() as session:
        stale_fail_job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc_b_id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND.value,
            status=JobStatus.CLAIMED.value,
            locked_by="w-fail-stale",
            failure_attempts=7,
            payload={"folder_id": str(folder_b_id), "_fencing_token": 4},
        )
        session.add(stale_fail_job)
        session.commit()
        stale_fail_id = stale_fail_job.id

    with Session() as session:
        fail_job(
            session,
            session.get(WorkerJob, stale_fail_id),
            "late terminal fail",
            worker_id="w-fail-stale",
            max_attempts=8,
            now=t_newer + timedelta(hours=2),
        )
        session.commit()

    with Session() as session:
        cp_b = session.get(SyncCheckpoint, {"account_id": acc_b_id, "folder_id": folder_b_id})
        assert cp_b.last_delta_settled_at == t_newer

    with Session() as session:
        acc_c, folder_c = _seed_account_with_inbox(session, prefix="prov-win-fail")
        session.add(
            SyncCheckpoint(
                account_id=acc_c.id,
                folder_id=folder_c.id,
                full_scan_complete=True,
                fencing_token=1,
                last_delta_settled_at=t_old,
            )
        )
        win_fail_job = WorkerJob(
            id=uuid.uuid4(),
            account_id=acc_c.id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            execution_origin=ExecutionOrigin.BACKGROUND.value,
            status=JobStatus.CLAIMED.value,
            locked_by="w-win-fail",
            failure_attempts=7,
            payload={"folder_id": str(folder_c.id)},
        )
        session.add(win_fail_job)
        session.commit()
        acc_c_id, folder_c_id, win_fail_id = acc_c.id, folder_c.id, win_fail_job.id

    with Session() as session:
        from mail_core.worker.handlers import _evaluate_result

        win_row = session.get(WorkerJob, win_fail_id)
        assert (
            _evaluate_result(
                session,
                win_row,
                {"status": "provider_error", "error": "boom", "fencing_token": 2},
                "w-win-fail",
            )
            is False
        )
        session.commit()

    with Session() as session:
        cp_c = session.get(SyncCheckpoint, {"account_id": acc_c_id, "folder_id": folder_c_id})
        assert cp_c.fencing_token == 2
        assert cp_c.last_delta_settled_at > t_newer
        # Stale token=1 arriving later in wall-clock time is blocked.
        assert (
            advance_delta_settlement_watermark(
                session,
                account_id=acc_c_id,
                folder_id=folder_c_id,
                settled_at=cp_c.last_delta_settled_at + timedelta(minutes=5),
                fencing_token=1,
            )
            is False
        )


def test_ac002_final_exhausted_page_commits_atomically_or_rolls_back_all(monkeypatch):
    """Finding 2: on exhausted=True via handle_job, apply_delta_page + ARCHIVE_MIME_BATCH
    + release_lease + complete_job + record_connectivity_success + watermark commit in ONE
    PostgreSQL transaction; a crash/exception before commit rolls all of them back.
    """
    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import ConnectivityState
    from mail_core.mail.storage.models import Account, AccountSyncLease, Message
    from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta
    from mail_core.sync import delta as delta_mod
    from mail_core.sync.jobs import claim_jobs, enqueue_job
    from mail_core.worker.handlers import handle_job

    Session = get_session_factory()
    t_old = datetime(2026, 11, 28, 1, 0, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)

    def _seed_case(prefix: str):
        with Session() as session:
            acc, folder = _seed_account_with_inbox(session, prefix=prefix)
            acc.connectivity_state = ConnectivityState.DEGRADED.value
            session.add(
                SyncCheckpoint(
                    account_id=acc.id,
                    folder_id=folder.id,
                    full_scan_complete=True,
                    cursor={"modseq": 10},
                    modseq=10,
                    last_delta_settled_at=t_old,
                )
            )
            req = SyncRequest(
                id=uuid.uuid4(),
                client_request_id=f"req-{prefix}-{uuid.uuid4().hex[:8]}",
                mode="delta",
                trigger="manual",
                state="queued",
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
                state="queued",
            )
            session.add(target)
            session.flush()
            job = enqueue_job(
                session,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                execution_origin=ExecutionOrigin.FOREGROUND,
                account_id=acc.id,
                payload={"folder_id": str(folder.id), "request_id": str(req.id)},
                dedupe_key=f"delta:{acc.id}:{folder.id}",
            )
            session.add(
                SyncRequestTargetJob(
                    id=uuid.uuid4(),
                    target_id=target.id,
                    job_id=job.id,
                    status="queued",
                )
            )
            session.commit()
            return acc.id, folder.id, req.id, target.id, job.id

    class _ExhaustedProvider:
        def __init__(self, remote_id: str, new_modseq: int):
            self._remote_id = remote_id
            self._new_modseq = new_modseq

        def delta_changes(self, _rid, _cur):
            return DeltaPage(
                changes=[
                    DeltaChange(
                        kind="upsert",
                        remote_id=self._remote_id,
                        meta=RemoteMessageMeta(
                            remote_id=self._remote_id,
                            subject="Atomic Test",
                            from_address="sender@example.test",
                            from_name="Sender",
                            sort_time=now,
                            is_read=False,
                            has_attachments=False,
                        ),
                    )
                ],
                next_cursor={"modseq": self._new_modseq},
                exhausted=True,
            )

    monkeypatch.setattr("mail_core.worker.handlers.get_credential_store", lambda: object())

    # Case 1: Nothing is committed before final session.commit() — all 6 effects appear together.
    acc1, fld1, req1, tgt1, job1 = _seed_case("atomic-ok")
    with Session() as session:
        claimed = claim_jobs(session, worker_id="w-atom1", limit=1, account_id=acc1)
        assert [j.id for j in claimed] == [job1]
        session.commit()

    monkeypatch.setattr(
        delta_mod,
        "build_provider",
        lambda *_a, **_k: _ExhaustedProvider("msg-atom-1", 20),
    )

    with Session() as session:
        job = session.get(WorkerJob, job1)
        assert handle_job(session, job, worker_id="w-atom1") is True

        # Before session.commit(): second PG session must observe NONE of the final commit's effects!
        with Session() as observer:
            cp_obs = observer.get(SyncCheckpoint, {"account_id": acc1, "folder_id": fld1})
            assert cp_obs.cursor == {"modseq": 10}
            assert cp_obs.last_delta_settled_at == t_old
            assert (
                observer.scalar(
                    select(Message).where(Message.account_id == acc1, Message.remote_id == "msg-atom-1")
                )
                is None
            )
            assert (
                observer.scalar(
                    select(WorkerJob).where(
                        WorkerJob.account_id == acc1,
                        WorkerJob.job_type == JobType.ARCHIVE_MIME_BATCH.value,
                    )
                )
                is None
            )
            lease_obs = observer.get(AccountSyncLease, acc1)
            assert lease_obs is not None and lease_obs.fencing_token == 1
            assert observer.get(WorkerJob, job1).status == JobStatus.CLAIMED.value
            assert observer.get(Account, acc1).connectivity_state == ConnectivityState.DEGRADED.value
            assert observer.get(SyncRequest, req1).state == "running"

        session.commit()

    # After ONE commit: all effects are persisted atomically.
    with Session() as verify:
        cp_v = verify.get(SyncCheckpoint, {"account_id": acc1, "folder_id": fld1})
        assert cp_v.cursor == {"modseq": 20}
        assert cp_v.last_delta_settled_at > t_old
        assert (
            verify.scalar(
                select(Message).where(Message.account_id == acc1, Message.remote_id == "msg-atom-1")
            )
            is not None
        )
        assert (
            verify.scalar(
                select(WorkerJob).where(
                    WorkerJob.account_id == acc1,
                    WorkerJob.job_type == JobType.ARCHIVE_MIME_BATCH.value,
                )
            )
            is not None
        )
        lease_v = verify.get(AccountSyncLease, acc1)
        assert lease_v is not None and lease_v.fencing_token == 2
        assert verify.get(WorkerJob, job1).status == JobStatus.DONE.value
        assert verify.get(Account, acc1).connectivity_state == ConnectivityState.CONNECTED.value
        assert verify.get(SyncRequest, req1).state == "complete"
        assert verify.get(SyncRequestTarget, tgt1).state == "complete"

    # Case 2: Simulated crash/exception before final commit rolls back cursor, message,
    # archive enqueue, lease release, job status, request status, and watermark together.
    acc2, fld2, req2, tgt2, job2 = _seed_case("atomic-crash")
    with Session() as session:
        claimed = claim_jobs(session, worker_id="w-atom2", limit=1, account_id=acc2)
        assert [j.id for j in claimed] == [job2]
        session.commit()

    monkeypatch.setattr(
        delta_mod,
        "build_provider",
        lambda *_a, **_k: _ExhaustedProvider("msg-atom-2", 30),
    )

    with Session() as session:
        job = session.get(WorkerJob, job2)
        assert handle_job(session, job, worker_id="w-atom2") is True
        # Simulate crash / commit failure before final PostgreSQL commit:
        session.rollback()

    with Session() as verify:
        cp_c = verify.get(SyncCheckpoint, {"account_id": acc2, "folder_id": fld2})
        assert cp_c.cursor == {"modseq": 10}
        assert cp_c.last_delta_settled_at == t_old
        assert (
            verify.scalar(
                select(Message).where(Message.account_id == acc2, Message.remote_id == "msg-atom-2")
            )
            is None
        )
        assert (
            verify.scalar(
                select(WorkerJob).where(
                    WorkerJob.account_id == acc2,
                    WorkerJob.job_type == JobType.ARCHIVE_MIME_BATCH.value,
                )
            )
            is None
        )
        lease_c = verify.get(AccountSyncLease, acc2)
        assert lease_c is not None and lease_c.fencing_token == 1
        assert verify.get(WorkerJob, job2).status == JobStatus.CLAIMED.value
        assert verify.get(Account, acc2).connectivity_state == ConnectivityState.DEGRADED.value
        assert verify.get(SyncRequest, req2).state == "running"
        assert verify.get(SyncRequestTarget, tgt2).state == "running"

    # Case 3: Exception inside complete_job during handle_job rolls back the entire
    # exhausted=True transaction (cursor, message, archive, lease release, watermark)
    # and keeps the job non-DONE for retry.
    acc3, fld3, req3, tgt3, job3 = _seed_case("atomic-exc")
    with Session() as session:
        claimed = claim_jobs(session, worker_id="w-atom3", limit=1, account_id=acc3)
        assert [j.id for j in claimed] == [job3]
        session.commit()

    monkeypatch.setattr(
        delta_mod,
        "build_provider",
        lambda *_a, **_k: _ExhaustedProvider("msg-atom-3", 40),
    )

    from mail_core.sync import checkpoints as checkpoints_mod

    orig_advance = checkpoints_mod.advance_delta_settlement_watermark

    def _boom_watermark(*_a, **_k):
        raise RuntimeError("simulated failure during final settlement")

    monkeypatch.setattr(checkpoints_mod, "advance_delta_settlement_watermark", _boom_watermark)
    try:
        with Session() as session:
            job = session.get(WorkerJob, job3)
            assert handle_job(session, job, worker_id="w-atom3") is False
            session.commit()
    finally:
        monkeypatch.setattr(checkpoints_mod, "advance_delta_settlement_watermark", orig_advance)

    with Session() as verify:
        cp_e = verify.get(SyncCheckpoint, {"account_id": acc3, "folder_id": fld3})
        assert cp_e.cursor == {"modseq": 10}
        assert cp_e.last_delta_settled_at == t_old
        assert (
            verify.scalar(
                select(Message).where(Message.account_id == acc3, Message.remote_id == "msg-atom-3")
            )
            is None
        )
        assert (
            verify.scalar(
                select(WorkerJob).where(
                    WorkerJob.account_id == acc3,
                    WorkerJob.job_type == JobType.ARCHIVE_MIME_BATCH.value,
                )
            )
            is None
        )
        lease_e = verify.get(AccountSyncLease, acc3)
        assert lease_e is not None and lease_e.fencing_token == 1
        job_e = verify.get(WorkerJob, job3)
        assert job_e.status == JobStatus.PENDING.value
        assert job_e.failure_attempts == 1
        assert "_fencing_token" not in job_e.payload
        assert verify.get(SyncRequest, req3).state == "queued"
        assert verify.get(SyncRequestTarget, tgt3).state == "queued"
