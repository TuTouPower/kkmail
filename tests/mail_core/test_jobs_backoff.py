"""fail_job backoff + reclaim limit (no Postgres required for pure helpers)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from mail_core.mail.domain.enums import JobStatus
from mail_core.sync.jobs import backoff_seconds, fail_job


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
    assert len(job.last_error) == 500  # redacted + truncated (MAX_ERROR_CHARS)
