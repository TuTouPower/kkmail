"""A347: enqueue merge must not pull a backoff job's run_after earlier."""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from mail_core.mail.domain.enums import JobStatus
from mail_core.sync.jobs import _merge_into_pending_job, fail_job

NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)

class _FakeSession:
    def flush(self): return None

def _job(*, run_after, payload=None, failure_attempts=0):
    return SimpleNamespace(payload=dict(payload or {}), priority=100, run_after=run_after, failure_attempts=failure_attempts, status=JobStatus.PENDING.value)

def test_merge_does_not_wake_backoff_marked_job():
    future = NOW + timedelta(seconds=60)
    job = _job(run_after=future, payload={"_backoff_until": future.isoformat(), "folder_id": "f1"}, failure_attempts=2)
    _merge_into_pending_job(job, payload={"request_id": "r2"}, priority=20, run_after=NOW)
    assert job.run_after == future
    assert job.payload["request_id"] == "r2"  # payload merge still happens
    assert job.payload["_backoff_until"] == future.isoformat()
    assert job.priority == 20

def test_merge_does_not_wake_legacy_backoff_job_without_marker():
    future = NOW + timedelta(seconds=60)
    job = _job(run_after=future, payload={}, failure_attempts=1)
    _merge_into_pending_job(job, payload={}, priority=100, run_after=NOW)
    assert job.run_after == future

def test_merge_still_wakes_non_backoff_job():
    future = NOW + timedelta(seconds=60)
    job = _job(run_after=future, payload={}, failure_attempts=0)
    _merge_into_pending_job(job, payload={}, priority=100, run_after=NOW)
    assert job.run_after == NOW

def test_fail_job_marks_backoff_until():
    job = SimpleNamespace(attempts=1, failure_attempts=0, status=JobStatus.CLAIMED.value, last_error=None, locked_by="w1", locked_at=NOW, run_after=NOW, payload={}, priority=100)
    fail_job(_FakeSession(), job, "boom", max_attempts=5, now=NOW)  # type: ignore[arg-type]
    assert job.status == JobStatus.PENDING.value
    assert job.payload["_backoff_until"] == job.run_after.isoformat()
    # And a subsequent merge cannot pull it earlier.
    _merge_into_pending_job(job, payload={}, priority=100, run_after=NOW)
    assert job.run_after == NOW + timedelta(seconds=1)
