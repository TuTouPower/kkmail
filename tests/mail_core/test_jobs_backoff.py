"""fail_job backoff + reclaim limit (no Postgres required for pure helpers)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from mail_core.mail.domain.enums import JobStatus
from mail_core.sync.jobs import backoff_seconds, fail_job, heartbeat_job_claim


class _FakeSession:
    def flush(self):
        return None


def test_backoff_seconds_grows_and_caps():
    assert backoff_seconds(1) == 1
    assert backoff_seconds(2) == 2
    assert backoff_seconds(3) == 4
    assert backoff_seconds(20) == 3600


def test_fail_job_requeues_until_max_attempts():
    job = SimpleNamespace(
        attempts=2,
        status=JobStatus.CLAIMED.value,
        last_error=None,
        locked_by="w1",
        locked_at=datetime.now(timezone.utc),
        run_after=datetime.now(timezone.utc),
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    fail_job(_FakeSession(), job, "boom", max_attempts=5, now=now)  # type: ignore[arg-type]
    assert job.status == JobStatus.PENDING.value
    assert job.locked_by is None
    assert job.run_after == now + timedelta(seconds=2)
    assert job.last_error == "boom"


def test_fail_job_permanent_when_attempts_exhausted():
    job = SimpleNamespace(
        attempts=8,
        status=JobStatus.CLAIMED.value,
        last_error=None,
        locked_by="w1",
        locked_at=datetime.now(timezone.utc),
        run_after=datetime.now(timezone.utc),
    )
    fail_job(_FakeSession(), job, "x" * 5000, max_attempts=8)  # type: ignore[arg-type]
    assert job.status == JobStatus.FAILED.value
    assert job.locked_by is None
    assert job.locked_at is None
    assert len(job.last_error) == 500  # redacted + truncated (MAX_ERROR_CHARS)


def test_claim_count_does_not_exhaust_failure_retry_budget():
    job = SimpleNamespace(
        attempts=25,
        failure_attempts=0,
        status=JobStatus.CLAIMED.value,
        last_error=None,
        locked_by="w1",
        locked_at=datetime.now(timezone.utc),
        run_after=datetime.now(timezone.utc),
    )
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    fail_job(_FakeSession(), job, "boom", max_attempts=3, now=now)  # type: ignore[arg-type]

    assert job.status == JobStatus.PENDING.value
    assert job.attempts == 25
    assert job.failure_attempts == 1
    assert job.run_after == now + timedelta(seconds=1)


def test_failure_cap_counts_real_failures():
    job = SimpleNamespace(
        attempts=25,
        failure_attempts=2,
        status=JobStatus.CLAIMED.value,
        last_error=None,
        locked_by="w1",
        locked_at=datetime.now(timezone.utc),
        run_after=datetime.now(timezone.utc),
    )

    fail_job(_FakeSession(), job, "boom", max_attempts=3)  # type: ignore[arg-type]

    assert job.status == JobStatus.FAILED.value
    assert job.failure_attempts == 3


def test_heartbeat_job_claim_uses_owner_and_lock_timestamp_cas():
    job_id = uuid.UUID(int=1)
    locked_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    heartbeat_at = locked_at + timedelta(seconds=30)

    class Result:
        rowcount = 1

    class Session:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return Result()

    session = Session()
    assert heartbeat_job_claim(
        session,
        job_id=job_id,
        worker_id="worker-1",
        locked_at=locked_at,
        now=heartbeat_at,
    ) == heartbeat_at

    statement = session.statement
    sql = str(statement).lower()
    params = statement.compile().params
    assert "worker_jobs.status" in sql
    assert "worker_jobs.locked_by" in sql
    assert "worker_jobs.locked_at" in sql
    assert job_id in params.values()
    assert "worker-1" in params.values()
    assert locked_at in params.values()
    assert heartbeat_at in params.values()
