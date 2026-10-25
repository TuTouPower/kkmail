"""Concurrency and atomicity tests for worker job successors and deduplicated wakeups."""

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobStatus, JobType
from mail_core.mail.storage.models import Account, WorkerJob
from mail_core.sync.jobs import claim_jobs, complete_job, enqueue_job

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _create_account(session):
    account = Account(
        id=uuid.uuid4(),
        email=f"job-test-{uuid.uuid4().hex[:6]}@example.com",
        provider="imap",
        sync_enabled=True,
    )
    session.add(account)
    session.flush()
    return account.id


def test_enqueue_during_complete_never_loses_wakeup():
    """P1-03: Two sessions interleaving claim/complete and enqueue_job never lose wakeup."""
    Session = get_session_factory()
    dedupe_key = f"test:wakeup:{uuid.uuid4().hex}"

    with Session() as s0:
        account_id = _create_account(s0)
        s0.commit()

    # 1. Enqueue initial job
    with Session() as s1:
        initial = enqueue_job(
            s1,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            account_id=account_id,
            payload={"folder_id": "f1", "counter": 1},
            priority=50,
            dedupe_key=dedupe_key,
        )
        s1.commit()

    # 2. Worker claims initial job
    with Session() as s1:
        claimed = claim_jobs(s1, worker_id="worker-w1", limit=1)
        assert len(claimed) == 1
        job1 = claimed[0]
        assert job1.status == JobStatus.CLAIMED.value
        job1_id = job1.id
        s1.commit()

    barrier1 = threading.Event()
    enqueue_done = threading.Event()

    def do_enqueue():
        with Session() as s2:
            barrier1.wait()
            # Enqueue while worker is completing or has completed
            job2 = enqueue_job(
                s2,
                job_type=JobType.SYNC_FOLDER_DELTA.value,
                account_id=account_id,
                payload={"folder_id": "f1", "counter": 2, "new_field": "val2"},
                priority=20,
                dedupe_key=dedupe_key,
            )
            s2.commit()
            enqueue_done.set()
            assert job2.status in (JobStatus.CLAIMED.value, JobStatus.PENDING.value)

    t = threading.Thread(target=do_enqueue)
    t.start()

    # Worker completes job1 in session 1
    with Session() as s1:
        job_to_complete = s1.scalar(select(WorkerJob).where(WorkerJob.id == job1_id))
        assert job_to_complete is not None
        barrier1.set()
        # Give t a moment to start enqueue_job and wait on row lock
        threading.Event().wait(0.05)
        successor = complete_job(s1, job_to_complete, worker_id="worker-w1")
        s1.commit()

    t.join(timeout=5)
    assert enqueue_done.is_set()

    # Verify that an active job exists (either created as successor or newly inserted pending)
    with Session() as s3:
        active_jobs = list(
            s3.scalars(
                select(WorkerJob)
                .where(WorkerJob.dedupe_key == dedupe_key)
                .where(WorkerJob.status == JobStatus.PENDING.value)
            ).all()
        )
        assert len(active_jobs) == 1, "Must have exactly 1 executable PENDING successor"
        active = active_jobs[0]
        # P2-01: verify new payload is preserved
        assert active.payload.get("counter") == 2
        assert active.payload.get("new_field") == "val2"
        # Verify priority took the higher urgency (20)
        assert active.priority == 20


def test_enqueue_never_returns_terminal_done_job():
    """P1-03: enqueue_job never returns a DONE job after waiting for lock."""
    Session = get_session_factory()
    dedupe_key = f"test:no-done:{uuid.uuid4().hex}"

    with Session() as s0:
        account_id = _create_account(s0)
        s0.commit()

    with Session() as s:
        job = enqueue_job(
            s,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            account_id=account_id,
            payload={"folder_id": "f1"},
            dedupe_key=dedupe_key,
        )
        s.commit()
        job_id = job.id

    with Session() as s:
        claimed = claim_jobs(s, worker_id="w-1", limit=1)
        job_claimed = claimed[0]
        complete_job(s, job_claimed, worker_id="w-1")
        s.commit()

    with Session() as s:
        new_job = enqueue_job(
            s,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            account_id=account_id,
            payload={"folder_id": "f1", "cycle": 2},
            dedupe_key=dedupe_key,
        )
        s.commit()
        assert new_job.id != job_id
        assert new_job.status == JobStatus.PENDING.value
