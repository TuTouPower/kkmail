"""Unit and integration tests for t063: Worker concurrent executor, traffic class admission, and per-account lease mutual exclusion."""

from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from mail_core.config import get_config
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobStatus, JobType
from mail_core.mail.storage.models import Account, MessageArchiveState, WorkerJob
from mail_core.providers.connection_slots import TrafficClass
from mail_core.sync.jobs import LEASE_JOB_TYPES, claim_jobs, complete_job, enqueue_job, fail_job
from mail_core.worker import main as worker_main

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_account(session, email: str | None = None) -> uuid.UUID:
    aid = uuid.uuid4()
    em = email or f"acc-{aid.hex[:8]}@example.com"
    acc = Account(id=aid, email=em, provider="imap", sync_enabled=True)
    session.add(acc)
    session.commit()
    return aid


def test_ac001_concurrent_capacity_reaches_and_caps_at_total_slots():
    """AC-001: Concurrent execution reaches total_slots and never exceeds total_slots."""
    cfg = get_config()
    total_slots = cfg.total_slots
    Session = get_session_factory()

    # Create total_slots + 4 distinct accounts and enqueue foreground tasks
    account_ids = []
    with Session() as session:
        for i in range(total_slots + 4):
            account_ids.append(_seed_account(session, f"acc-ac001-{i}-{uuid.uuid4().hex[:6]}@test.com"))

    with Session() as session:
        for aid in account_ids:
            enqueue_job(
                session,
                job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
                account_id=aid,
                priority=20,
            )
        session.commit()

    peak_concurrency = 0
    active_now = 0
    concurrency_lock = threading.Lock()
    barrier = threading.Barrier(total_slots)
    finish_event = threading.Event()

    def fake_handle(session, job, *args, **kwargs):
        nonlocal peak_concurrency, active_now
        with concurrency_lock:
            active_now += 1
            if active_now > peak_concurrency:
                peak_concurrency = active_now
        try:
            barrier.wait(timeout=3.0)
        except Exception:
            pass
        finish_event.wait(timeout=3.0)
        with concurrency_lock:
            active_now -= 1
        return True

    worker_main._in_flight_jobs.clear()
    with patch("mail_core.worker.handlers.handle_job", side_effect=fake_handle):
        thread = threading.Thread(
            target=lambda: worker_main.run(poll_interval_s=0.1),
            daemon=True,
        )
        thread.start()

        # Wait until peak reaches total_slots
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            with concurrency_lock:
                if peak_concurrency >= total_slots:
                    break
            time.sleep(0.05)

        finish_event.set()
        time.sleep(0.5)
        worker_main.request_stop()
        thread.join(timeout=3.0)

    assert peak_concurrency == total_slots, f"expected peak concurrency {total_slots}, got {peak_concurrency}"


def test_ac002_ac003_background_admission_and_foreground_starvation_prevention():
    """AC-002, AC-003: Background batch jobs cap at background_limit; priority=10 foreground runs in <1s."""
    cfg = get_config()
    total_slots = cfg.total_slots
    background_limit = total_slots - cfg.background_start_slot
    Session = get_session_factory()

    with Session() as session:
        aid = _seed_account(session, f"acc-ac002-{uuid.uuid4().hex[:6]}@test.com")

    # Enqueue 15 routine background archive jobs
    with Session() as session:
        for i in range(15):
            enqueue_job(
                session,
                job_type=JobType.ARCHIVE_MIME_BATCH.value,
                account_id=aid,
                payload={"batch_index": i},  # no message_id -> BACKGROUND
                priority=60,
            )
        session.commit()

    bg_peak = 0
    bg_active = 0
    bg_lock = threading.Lock()
    bg_started = threading.Event()
    bg_finish = threading.Event()

    fg_handled = threading.Event()
    fg_job_id = None

    def fake_handle(session, job, *args, **kwargs):
        nonlocal bg_peak, bg_active
        payload = job.payload or {}
        if job.job_type == JobType.ARCHIVE_MIME_BATCH.value and not payload.get("message_id"):
            with bg_lock:
                bg_active += 1
                if bg_active > bg_peak:
                    bg_peak = bg_active
            if bg_peak >= background_limit:
                bg_started.set()
            bg_finish.wait(timeout=5.0)
            with bg_lock:
                bg_active -= 1
            return True
        else:
            if job.id == fg_job_id:
                fg_handled.set()
            return True

    worker_main._in_flight_jobs.clear()
    with patch("mail_core.worker.handlers.handle_job", side_effect=fake_handle):
        thread = threading.Thread(
            target=lambda: worker_main.run(poll_interval_s=0.1),
            daemon=True,
        )
        thread.start()

        try:
            # Wait until background jobs occupy maximum allowed slots
            assert bg_started.wait(timeout=4.0), "Background jobs failed to reach background_limit"
            assert bg_peak == background_limit, f"Background tasks must cap at {background_limit}, reached {bg_peak}"

            # Now enqueue an on-demand priority=10 archive job (foreground)
            t0 = time.monotonic()
            with Session() as session:
                fg_job = enqueue_job(
                    session,
                    job_type=JobType.ARCHIVE_MIME_BATCH.value,
                    account_id=aid,
                    payload={"message_id": str(uuid.uuid4())},  # has message_id -> FOREGROUND
                    priority=10,
                )
                session.commit()
                fg_job_id = fg_job.id

            assert fg_handled.wait(timeout=1.0), "Priority=10 foreground job failed to start within 1s while background saturated"
            fg_elapsed = time.monotonic() - t0
            assert fg_elapsed < 1.0, f"Foreground job took {fg_elapsed:.2f}s to start"
        finally:
            bg_finish.set()
            worker_main.request_stop()
            thread.join(timeout=3.0)


def test_ac004_priority_and_fifo_claim_order():
    """AC-004: Jobs are claimed strictly in priority ascending, created_at ascending order."""
    Session = get_session_factory()
    w_id = f"worker-order-{uuid.uuid4().hex[:6]}"

    with Session() as session:
        aid1 = _seed_account(session)
        aid2 = _seed_account(session)
        aid3 = _seed_account(session)

        # Enqueue: priority 50, priority 10, priority 50 (earlier vs later)
        j1 = enqueue_job(session, job_type=JobType.SYNC_ACCOUNT_FOLDERS.value, account_id=aid1, priority=50)
        time.sleep(0.01)
        j2 = enqueue_job(session, job_type=JobType.SYNC_ACCOUNT_FOLDERS.value, account_id=aid2, priority=10)
        time.sleep(0.01)
        j3 = enqueue_job(session, job_type=JobType.SYNC_ACCOUNT_FOLDERS.value, account_id=aid3, priority=50)
        session.commit()
        id1, id2, id3 = j1.id, j2.id, j3.id

    with Session() as session:
        claimed = claim_jobs(session, worker_id=w_id, limit=3)
        claimed_ids = [j.id for j in claimed]
        session.commit()

    # Priority 10 must come first; among priority 50, j1 (earlier) must come before j3 (later)
    assert claimed_ids == [id2, id1, id3], f"unexpected claim order: {claimed_ids}"


def test_ac005_per_account_lease_mutual_exclusion():
    """AC-005: Two lease jobs for the same account cannot be claimed concurrently; different accounts can."""
    Session = get_session_factory()
    w_id = f"worker-lease-{uuid.uuid4().hex[:6]}"

    with Session() as session:
        aid_a = _seed_account(session)
        aid_b = _seed_account(session)

        # Acc A has two lease jobs: delta and metadata
        j_a1 = enqueue_job(session, job_type=JobType.SYNC_FOLDER_DELTA.value, account_id=aid_a, priority=20)
        j_a2 = enqueue_job(session, job_type=JobType.SYNC_FOLDER_METADATA.value, account_id=aid_a, priority=25)
        # Acc A also has an archive job (non-lease)
        j_a_arch = enqueue_job(session, job_type=JobType.ARCHIVE_MIME_BATCH.value, account_id=aid_a, priority=30)

        # Acc B has one lease job
        j_b1 = enqueue_job(session, job_type=JobType.SYNC_FOLDER_DELTA.value, account_id=aid_b, priority=20)
        session.commit()
        id_a1, id_a2, id_a_arch, id_b1 = j_a1.id, j_a2.id, j_a_arch.id, j_b1.id

    with Session() as session:
        # Claim first batch
        batch1 = claim_jobs(session, worker_id=w_id, limit=4, exclude_busy_lease_accounts=True)
        batch1_ids = {j.id for j in batch1}
        session.commit()

    # j_a1 and j_b1 should be claimed. j_a_arch should be claimed.
    # j_a2 MUST NOT be claimed because acc_a already has a lease job claimed!
    assert id_a1 in batch1_ids
    assert id_b1 in batch1_ids
    assert id_a_arch in batch1_ids
    assert id_a2 not in batch1_ids, "j_a2 for acc_a must not be claimed while j_a1 is claimed"

    # Now complete j_a1
    with Session() as session:
        row = session.get(WorkerJob, id_a1)
        row.status = JobStatus.DONE.value
        session.commit()

    # Now j_a2 can be claimed
    with Session() as session:
        batch2 = claim_jobs(session, worker_id=w_id, limit=2, exclude_busy_lease_accounts=True)
        batch2_ids = {j.id for j in batch2}
        session.commit()

    assert id_a2 in batch2_ids, "j_a2 must be claimable once previous lease job is DONE"


def test_ac006_execution_owner_granularity_protects_fencing():
    """AC-006: Concurrent tasks in same worker use unique execution_owner preventing lease fencing stomping."""
    from mail_core.sync.leases import acquire_lease, release_lease

    Session = get_session_factory()
    w_id = "worker-ac006"

    with Session() as session:
        aid1 = _seed_account(session)
        aid2 = _seed_account(session)

    # Task 1 for acc1 and Task 2 for acc2 acquire lease concurrently with distinct execution owners
    owner1 = f"{w_id}:{uuid.uuid4()}"
    owner2 = f"{w_id}:{uuid.uuid4()}"

    with Session() as s1:
        lease1 = acquire_lease(s1, account_id=aid1, owner_id=owner1, ttl=timedelta(seconds=30))
        s1.commit()

    with Session() as s2:
        lease2 = acquire_lease(s2, account_id=aid2, owner_id=owner2, ttl=timedelta(seconds=30))
        s2.commit()

    assert lease1.owner_id == owner1
    assert lease2.owner_id == owner2
    assert lease1.fencing_token == 1
    assert lease2.fencing_token == 1

    # Releasing lease1 does not affect lease2
    with Session() as s1:
        release_lease(s1, account_id=aid1, owner_id=owner1, fencing_token=lease1.fencing_token)
        s1.commit()

    with Session() as s2:
        from mail_core.sync.leases import heartbeat_lease

        refreshed = heartbeat_lease(s2, account_id=aid2, owner_id=owner2, fencing_token=lease2.fencing_token)
        s2.commit()
        assert refreshed is not None


def test_ac007_unified_heartbeat_keeps_in_flight_claims_alive():
    """AC-007: UnifiedClaimHeartbeatLoop continually refreshes locked_at for in-flight jobs."""
    Session = get_session_factory()
    w_id = f"worker-hb-{uuid.uuid4().hex[:6]}"

    with Session() as session:
        aid = _seed_account(session)
        job = enqueue_job(session, job_type=JobType.GC_BLOBS.value, account_id=aid)
        session.commit()
        jid = job.id

    with Session() as session:
        claimed = claim_jobs(session, worker_id=w_id, limit=1)
        initial_locked_at = claimed[0].locked_at
        session.commit()

    # Register in in-flight jobs and start unified heartbeat loop with fast 0.2s interval
    token = worker_main.InFlightJob(
        job_id=jid,
        worker_id=w_id,
        traffic_class=TrafficClass.FOREGROUND,
        locked_at=initial_locked_at,
    )
    with worker_main._in_flight_lock:
        worker_main._in_flight_jobs[jid] = token

    hb_loop = worker_main.UnifiedClaimHeartbeatLoop(Session, worker_id=w_id, interval_s=0.2)
    hb_loop.start()

    time.sleep(0.7)
    hb_loop.stop()

    with worker_main._in_flight_lock:
        worker_main._in_flight_jobs.pop(jid, None)

    with Session() as session:
        row = session.get(WorkerJob, jid)
        assert row.locked_at > initial_locked_at, "Heartbeat loop must update locked_at in database"


def test_ac008_exception_isolation_among_concurrent_tasks():
    """AC-008: Uncaught exception in one job marks only that job failed; sibling jobs succeed."""
    Session = get_session_factory()

    with Session() as session:
        aid1 = _seed_account(session)
        aid2 = _seed_account(session)
        j_bad = enqueue_job(session, job_type=JobType.GC_BLOBS.value, account_id=aid1, payload={"fail": True})
        j_good = enqueue_job(session, job_type=JobType.GC_BLOBS.value, account_id=aid2, payload={"fail": False})
        session.commit()
        bad_id, good_id = j_bad.id, j_good.id

    def fake_handle(session, job, *args, **kwargs):
        payload = job.payload or {}
        if payload.get("fail"):
            raise RuntimeError("intentional explosion")
        complete_job(session, job, worker_id="w-iso")
        return True

    worker_main._in_flight_jobs.clear()
    with patch("mail_core.worker.handlers.handle_job", side_effect=fake_handle):
        result = worker_main._tick("w-iso", block=True, limit=2)

    assert result.claimed == 2
    assert result.handled == 1

    with Session() as session:
        bad_row = session.get(WorkerJob, bad_id)
        good_row = session.get(WorkerJob, good_id)
        # Sibling task succeeded
        assert good_row.status == JobStatus.DONE.value
        # Bad task failed and requeued with backoff attempt incremented
        assert bad_row.status == JobStatus.PENDING.value
        assert bad_row.failure_attempts == 1
        assert "RuntimeError" in str(bad_row.last_error)


def test_ac010_graceful_shutdown_waits_for_in_flight():
    """AC-010: Shutdown stops new claims and allows running tasks to complete normally."""
    Session = get_session_factory()
    with Session() as session:
        aid = _seed_account(session)
        job = enqueue_job(session, job_type=JobType.GC_BLOBS.value, account_id=aid)
        session.commit()
        jid = job.id

    task_completed = threading.Event()

    def fake_handle(session, j, worker_id="worker", *args, **kwargs):
        time.sleep(0.3)
        complete_job(session, j, worker_id=worker_id)
        task_completed.set()
        return True

    worker_main._in_flight_jobs.clear()
    with patch("mail_core.worker.handlers.handle_job", side_effect=fake_handle):
        thread = threading.Thread(target=lambda: worker_main.run(poll_interval_s=0.1), daemon=True)
        thread.start()

        # Let worker claim the job then request stop
        time.sleep(0.15)
        worker_main.request_stop()
        thread.join(timeout=3.0)

    assert task_completed.is_set(), "In-flight task must finish during graceful shutdown"
    with Session() as session:
        row = session.get(WorkerJob, jid)
        assert row.status == JobStatus.DONE.value
