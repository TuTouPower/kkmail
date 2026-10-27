"""A148: reclaim_stale_claims must count failures and terminate crash loops."""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from mail_core.mail.domain.enums import JobStatus
from mail_core.sync.jobs import reclaim_stale_claims

NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)

class _Result:
    def __init__(self, rows): self._rows = rows
    def all(self): return list(self._rows)

class _FakeSession:
    def __init__(self, rows): self._rows = rows
    def scalars(self, stmt, *a, **k): return _Result(self._rows)
    def execute(self, stmt, *a, **k): return _Result([])
    def flush(self): return None

def _job(failure_attempts):
    return SimpleNamespace(id=uuid.uuid4(), status=JobStatus.CLAIMED.value, locked_by="dead", locked_at=NOW - timedelta(hours=1), last_error=None, failure_attempts=failure_attempts, attempts=1, run_after=NOW - timedelta(hours=1), payload={})

def test_reclaim_increments_failure_attempts_and_requeues_below_cap():
    job = _job(failure_attempts=0)
    n = reclaim_stale_claims(_FakeSession([job]), older_than=timedelta(minutes=5), now=NOW, max_attempts=3)  # type: ignore[arg-type]
    assert n == 1
    assert job.failure_attempts == 1
    assert job.status == JobStatus.PENDING.value
    assert job.locked_by is None

def test_reclaim_at_cap_settles_terminal_failed():
    job = _job(failure_attempts=2)
    n = reclaim_stale_claims(_FakeSession([job]), older_than=timedelta(minutes=5), now=NOW, max_attempts=3)  # type: ignore[arg-type]
    assert n == 1
    assert job.failure_attempts == 3
    assert job.status == JobStatus.FAILED.value
    assert job.locked_by is None and job.locked_at is None
    assert "reclaimed_stale_claim" in (job.last_error or "")

def test_repeated_reclaims_eventually_terminate():
    job = _job(failure_attempts=0)
    for _ in range(2):
        job.status = JobStatus.CLAIMED.value; job.locked_by = "dead"; job.locked_at = NOW - timedelta(hours=1)
        reclaim_stale_claims(_FakeSession([job]), older_than=timedelta(minutes=5), now=NOW, max_attempts=3)  # type: ignore[arg-type]
        assert job.status == JobStatus.PENDING.value
    job.status = JobStatus.CLAIMED.value; job.locked_by = "dead"; job.locked_at = NOW - timedelta(hours=1)
    reclaim_stale_claims(_FakeSession([job]), older_than=timedelta(minutes=5), now=NOW, max_attempts=3)  # type: ignore[arg-type]
    assert job.status == JobStatus.FAILED.value
    assert job.failure_attempts == 3
