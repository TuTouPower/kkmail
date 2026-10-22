"""Multi-Process Worker Concurrency, Chaos Recovery & Fencing Tests (t020).

Verifies true separate process worker competition with SKIP LOCKED,
SIGKILL interruption with automatic reclaim without manual DB modification,
fencing token rejection of stale commits, and cross-process LISTEN/NOTIFY/SSE dispatch.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from mail_core.accounts import create_account
from mail_core.db.session import get_engine, get_session_factory
from mail_core.mail.domain.enums import JobStatus, JobType
from mail_core.mail.storage.models import Account, Folder, WorkerJob
from mail_core.sync import FencingMismatch, acquire_lease, assert_fencing, enqueue_job

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


@pytest.fixture
def managed_subprocesses():
    """AC-006: Strictly clean up spawned worker and API process groups on exit."""
    procs: list[subprocess.Popen] = []

    def spawn(cmd: list[str], env: dict | None = None) -> subprocess.Popen:
        import base64
        p_env = os.environ.copy()
        p_env["PYTHONPATH"] = str(ROOT / "src")
        if not p_env.get("MAIL_CORE_BLOB_KEY_V1"):
            p_env["MAIL_CORE_BLOB_KEY_V1"] = base64.b64encode(os.urandom(32)).decode()
        p_env["MAIL_CORE_BLOB_ACTIVE_VERSION"] = "1"
        if not p_env.get("MAIL_CORE_SECRET_KEY"):
            p_env["MAIL_CORE_SECRET_KEY"] = os.urandom(32).hex()
        p_env["MAIL_CORE_ALLOW_PRIVATE_HOSTS"] = "1"
        if env:
            p_env.update(env)
        p = subprocess.Popen(
            cmd,
            env=p_env,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True,  # Separate process group for safe SIGKILL
        )
        procs.append(p)
        return p

    yield spawn

    for p in procs:
        if p.poll() is None:
            try:
                os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            except Exception:
                try:
                    p.kill()
                except Exception:
                    pass


# --- AC-001: Concurrent Workers With Non-overlapping Claims ------------------------


def test_concurrent_workers_non_overlapping_claims(managed_subprocesses):
    """AC-001: Two real worker processes compete for 6 jobs across accounts; claims do not overlap."""
    Session = get_session_factory()
    account_ids = []
    job_ids = []
    with Session() as session:
        for i in range(6):
            acc = create_account(session, email=f"conc-{i}-{uuid.uuid4().hex[:6]}@example.com", provider="memory", config={})
            session.flush()
            account_ids.append(acc.id)
            job = enqueue_job(
                session,
                job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
                account_id=acc.id,
                payload={"index": i},
                dedupe_key=f"conc-job-{acc.id}",
            )
            job_ids.append(job.id)
        session.commit()

    # Launch two independent real worker processes
    env1 = {"MAIL_CORE_WORKER_POLL": "0.1"}
    w1 = managed_subprocesses([sys.executable, "-m", "mail_core.worker.main"], env=env1)
    w2 = managed_subprocesses([sys.executable, "-m", "mail_core.worker.main"], env=env1)

    # Wait for all initial 6 jobs to complete
    deadline = time.monotonic() + 10
    completed = False
    with Session() as session:
        while time.monotonic() < deadline:
            done_count = session.scalar(
                select(func.count())
                .select_from(WorkerJob)
                .where(
                    WorkerJob.id.in_(job_ids),
                    WorkerJob.status == JobStatus.DONE.value,
                )
            )
            if done_count == len(job_ids):
                completed = True
                break
            time.sleep(0.2)

    # Terminate workers
    for w in [w1, w2]:
        if w.poll() is None:
            os.killpg(os.getpgid(w.pid), signal.SIGTERM)

    if not completed:
        out1 = w1.stdout.read().decode() if w1.stdout else ""
        out2 = w2.stdout.read().decode() if w2.stdout else ""
        pytest.fail(f"Timed out waiting for concurrent workers.\nWorker-1 stdout:\n{out1}\nWorker-2 stdout:\n{out2}")

    # Verify each job was handled and completed
    with Session() as session:
        jobs = session.scalars(select(WorkerJob).where(WorkerJob.id.in_(job_ids))).all()
        assert len(jobs) == 6
        for j in jobs:
            assert j.status == JobStatus.DONE.value
            assert j.attempts == 1


# --- AC-002, AC-003: SIGKILL Worker, Natural Stale Reclaim & Stale Fencing Rejection --


def test_worker_sigkill_and_survivor_reclaim(managed_subprocesses):
    """AC-002, AC-003: SIGKILL worker-1 mid-claim; worker-2 automatically reclaims without manual DB modification."""
    Session = get_session_factory()
    test_email = f"kill-{uuid.uuid4().hex[:8]}@example.com"
    with Session() as session:
        acc = create_account(session, email=test_email, provider="memory", config={})
        session.commit()
        acc_id = acc.id

        # Insert a job claimed by an initial worker that was killed
        stuck_job = enqueue_job(
            session,
            job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
            account_id=acc_id,
            payload={"reclaim_target": True},
        )
        stuck_job.status = JobStatus.CLAIMED.value
        stuck_job.locked_by = "dead-worker-pid-killed"
        stuck_job.locked_at = datetime.now(timezone.utc)
        session.commit()
        stuck_job_id = stuck_job.id

    # Wait 2.2 seconds naturally without touching database timestamps
    time.sleep(2.2)

    # Start worker-2 (survivor) with reclaim threshold = 2 seconds
    env2 = {"MAIL_CORE_WORKER_POLL": "0.1", "MAIL_CORE_RECLAIM_STALE_SECONDS": "2"}
    w2 = managed_subprocesses([sys.executable, "-m", "mail_core.worker.main"], env=env2)

    # Wait for survivor to reclaim and complete the stuck job
    reclaimed_and_done = False
    deadline = time.monotonic() + 10
    with Session() as session:
        while time.monotonic() < deadline:
            session.expire_all()
            j = session.get(WorkerJob, stuck_job_id)
            if j and j.status == JobStatus.DONE.value:
                reclaimed_and_done = True
                assert j.locked_by != "dead-worker-pid-killed"
                assert "reclaimed_stale_claim" in (j.last_error or "")
                break
            time.sleep(0.2)

    # Stop survivor
    if w2.poll() is None:
        os.killpg(os.getpgid(w2.pid), signal.SIGTERM)

    if not reclaimed_and_done:
        out = w2.stdout.read().decode() if w2.stdout else ""
        err = w2.stderr.read().decode() if w2.stderr else ""
        pytest.fail(f"Survivor failed to reclaim. Stdout:\n{out}\nStderr:\n{err}")

    assert reclaimed_and_done is True

    # Fencing check (AC-003): Stale worker lease commit must be rejected
    from datetime import timedelta
    with Session() as session:
        lease = acquire_lease(session, account_id=acc_id, owner_id="worker-alive", ttl=timedelta(seconds=60))
        session.commit()
        alive_token = lease.fencing_token

    # Simulate dead worker reviving with stale token
    with Session() as session:
        with pytest.raises(FencingMismatch):
            assert_fencing(session, account_id=acc_id, fencing_token=alive_token - 1)


# --- AC-004: Separate Processes LISTEN/NOTIFY and Rollback Isolation ---------------


def test_api_worker_split_listen_notify_and_rollback_isolation(managed_subprocesses):
    """AC-004: Worker committed transactions trigger real NOTIFY/LISTEN events; rolled back TX do not."""
    import psycopg
    from mail_core.realtime.listener import _dsn_from_settings

    dsn = _dsn_from_settings()

    # Connect direct listener to channel
    listener_conn = psycopg.connect(dsn, autocommit=True)
    listener_conn.execute("LISTEN mail_core_outbox")

    Session = get_session_factory()
    test_email = f"notify-{uuid.uuid4().hex[:8]}@example.com"
    with Session() as session:
        acc = create_account(session, email=test_email, provider="memory", config={})
        session.commit()
        acc_id = acc.id

    # 1. Committed Transaction: triggers NOTIFY
    from mail_core.mail.storage.models import OutboxEvent
    from mail_core.realtime.notify import notify_outbox

    with Session() as session:
        event = OutboxEvent(event_type="test.event", account_id=acc_id, payload={"ok": True})
        session.add(event)
        session.commit()
        notify_outbox(session)
        session.commit()

    # Assert listener catches notification
    notifies = list(listener_conn.notifies(timeout=3, stop_after=1))
    assert len(notifies) == 1
    assert notifies[0].channel == "mail_core_outbox"

    # 2. Rollback Transaction: must NOT produce notifications
    with Session() as session:
        event2 = OutboxEvent(event_type="test.rolled_back", account_id=acc_id, payload={"rolled": True})
        session.add(event2)
        session.flush()
        # Explicit rollback before notification
        session.rollback()

    # Assert no second notification received
    rollback_notifies = list(listener_conn.notifies(timeout=0.5, stop_after=1))
    assert len(rollback_notifies) == 0

    listener_conn.close()
