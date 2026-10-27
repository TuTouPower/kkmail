"""Unit tests for periodic inbox sync scheduler and staggered dispatch (t057 AC-001, AC-002, AC-006, AC-007)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobStatus, JobType, SyncStatus
from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint, WorkerJob
from mail_core.worker.main import schedule_periodic_inbox_sync

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_account_with_inbox(
    session,
    *,
    email_prefix: str = "sched",
    sync_enabled: bool = True,
    folder_role: str = "inbox",
    folder_status: str = SyncStatus.IDLE.value,
) -> tuple[Account, Folder]:
    acc = Account(
        id=uuid.uuid4(),
        email=f"{email_prefix}-{uuid.uuid4().hex[:6]}@example.com",
        provider="stub",
        credential_ref=f"ref-{uuid.uuid4().hex[:6]}",
        sync_enabled=sync_enabled,
    )
    session.add(acc)
    session.flush()

    folder = Folder(
        id=uuid.uuid4(),
        account_id=acc.id,
        remote_id=f"remote-folder-{uuid.uuid4().hex[:6]}",
        name="Inbox" if folder_role == "inbox" else "Sent",
        role=folder_role,
        sync_status=folder_status,
    )
    session.add(folder)
    session.flush()
    return acc, folder


def test_ac001_schedules_overdue_inbox():
    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session)
        acc_id, folder_id = acc.id, folder.id
        # Checkpoint last synced 1500 seconds ago (> 1200s)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=1500)
        cp = SyncCheckpoint(
            account_id=acc_id,
            folder_id=folder_id,
            full_scan_complete=True,
            updated_at=old_time,
        )
        session.add(cp)
        session.commit()

    with Session() as session:
        enqueued = schedule_periodic_inbox_sync(session, poll_interval_s=1200.0)
        assert enqueued >= 1

        job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == acc_id,
                WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
                WorkerJob.dedupe_key == f"delta:{acc_id}:{folder_id}",
            )
        )
        assert job is not None
        assert job.status == JobStatus.PENDING.value
        assert job.priority == 75
        assert job.payload == {"folder_id": str(folder_id)}


def test_ac001_ignores_disabled_accounts_and_paused_or_non_inbox_folders():
    Session = get_session_factory()
    with Session() as session:
        # 1. Disabled account
        acc_disabled, f_disabled = _seed_account_with_inbox(session, sync_enabled=False)
        # 2. Paused inbox folder
        acc_paused, f_paused = _seed_account_with_inbox(session, folder_status=SyncStatus.PAUSED.value)
        # 3. Non-inbox folder (sent)
        acc_sent, f_sent = _seed_account_with_inbox(session, folder_role="sent")
        session.commit()
        targets = [
            (acc_disabled.id, f_disabled.id),
            (acc_paused.id, f_paused.id),
            (acc_sent.id, f_sent.id),
        ]

    with Session() as session:
        schedule_periodic_inbox_sync(session, poll_interval_s=1200.0)

        for target_acc_id, target_f_id in targets:
            job = session.scalar(
                select(WorkerJob).where(
                    WorkerJob.account_id == target_acc_id,
                    WorkerJob.dedupe_key == f"delta:{target_acc_id}:{target_f_id}",
                )
            )
            assert job is None, f"Should not schedule job for account {target_acc_id}"


def test_ac002_staggers_multiple_accounts():
    Session = get_session_factory()
    account_ids: list[uuid.UUID] = []
    with Session() as session:
        for i in range(5):
            acc, folder = _seed_account_with_inbox(session, email_prefix=f"stagger{i}")
            account_ids.append(acc.id)
        session.commit()

    with Session() as session:
        now = datetime.now(timezone.utc)
        enqueued = schedule_periodic_inbox_sync(session, poll_interval_s=1200.0, now=now)
        assert enqueued == 5

        jobs = list(
            session.scalars(
                select(WorkerJob)
                .where(
                    WorkerJob.account_id.in_(account_ids),
                    WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
                )
                .order_by(WorkerJob.run_after.asc())
            ).all()
        )
        assert len(jobs) == 5

        # Verify staggering: run_after must not all be identical
        run_afters = [j.run_after for j in jobs]
        assert len(set(run_afters)) == 5
        # The earliest run_after should be close to now, and subsequent ones spaced out
        for idx in range(len(run_afters) - 1):
            assert run_afters[idx + 1] > run_afters[idx]


def test_ac006_deduplicates_in_flight_and_heals_after_terminal_failure():
    Session = get_session_factory()
    with Session() as session:
        acc, folder = _seed_account_with_inbox(session)
        acc_id, folder_id = acc.id, folder.id
        # 1. Simulate an in-flight PENDING job: scheduler must NOT duplicate it
        job_pending = WorkerJob(
            account_id=acc_id,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            dedupe_key=f"delta:{acc_id}:{folder_id}",
            status=JobStatus.PENDING.value,
            payload={"folder_id": str(folder_id)},
        )
        session.add(job_pending)
        session.commit()
        job_pending_id = job_pending.id

    with Session() as session:
        enqueued = schedule_periodic_inbox_sync(session, poll_interval_s=1200.0)
        # Did not enqueue because already pending
        jobs = list(
            session.scalars(
                select(WorkerJob).where(WorkerJob.dedupe_key == f"delta:{acc_id}:{folder_id}")
            ).all()
        )
        assert len(jobs) == 1
        assert jobs[0].id == job_pending_id

    # 2. Simulate the job failing terminally (FAILED status) more than 1200s ago
    with Session() as session:
        j = session.get(WorkerJob, job_pending_id)
        j.status = JobStatus.FAILED.value
        j.updated_at = datetime.now(timezone.utc) - timedelta(seconds=1300)
        session.commit()

    with Session() as session:
        # Scheduler must heal: overdue since last success/updated_at, so enqueue a new job
        enqueued_heal = schedule_periodic_inbox_sync(session, poll_interval_s=1200.0)
        active_jobs = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.dedupe_key == f"delta:{acc_id}:{folder_id}",
                    WorkerJob.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value]),
                )
            ).all()
        )
        assert len(active_jobs) == 1
        assert active_jobs[0].id != job_pending_id


def test_ac007_poll_interval_env_override(monkeypatch):
    from mail_core.worker.main import _positive_float_setting, DEFAULT_INBOX_POLL_INTERVAL_S

    # Default is 1200.0
    monkeypatch.delenv("MAIL_CORE_INBOX_POLL_INTERVAL_S", raising=False)
    assert _positive_float_setting("MAIL_CORE_INBOX_POLL_INTERVAL_S", DEFAULT_INBOX_POLL_INTERVAL_S) == 1200.0

    # Overridden to custom value
    monkeypatch.setenv("MAIL_CORE_INBOX_POLL_INTERVAL_S", "600.0")
    assert _positive_float_setting("MAIL_CORE_INBOX_POLL_INTERVAL_S", DEFAULT_INBOX_POLL_INTERVAL_S) == 600.0

    # Invalid env falls back to default
    monkeypatch.setenv("MAIL_CORE_INBOX_POLL_INTERVAL_S", "invalid_value")
    assert _positive_float_setting("MAIL_CORE_INBOX_POLL_INTERVAL_S", DEFAULT_INBOX_POLL_INTERVAL_S) == 1200.0
