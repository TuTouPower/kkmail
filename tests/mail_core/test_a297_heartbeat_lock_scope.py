"""A297: claim heartbeat DB refresh must not hold claim_times_lock across IO."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from mail_core.worker import main as worker_main


def test_heartbeat_db_refresh_runs_outside_claim_times_lock(monkeypatch):
    monkeypatch.setattr(worker_main, "_claim_heartbeat_interval_s", lambda: 0.01)
    job_ok, job_lost = uuid.uuid4(), uuid.uuid4()
    t0 = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 10, 25, 10, 1, tzinfo=timezone.utc)
    claim_times = {job_ok: t0, job_lost: t0}
    claim_lock = threading.Lock()
    stop_event = threading.Event()
    lock_free_during_refresh: list[bool] = []
    refreshed_once = threading.Event()

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def commit(self):
            pass

    def refresh(_session, *, job_id, worker_id, locked_at, now):
        # If the heartbeat thread still held claim_times_lock across this DB
        # call, the main thread's claim validation would be blocked; probe it.
        acquired = claim_lock.acquire(timeout=0.5)
        lock_free_during_refresh.append(acquired)
        if acquired:
            claim_lock.release()
        refreshed_once.set()
        return t1 if job_id == job_ok else None

    with patch("mail_core.sync.jobs.heartbeat_job_claim", side_effect=refresh):
        thread = threading.Thread(
            target=worker_main._heartbeat_claims,
            args=(
                lambda: Session(),
                [(job_ok, "worker-1", t0), (job_lost, "worker-1", t0)],
                claim_times,
                claim_lock,
                stop_event,
            ),
            daemon=True,
        )
        thread.start()
        try:
            assert refreshed_once.wait(timeout=2)
            # Let the writeback phase complete before stopping.
            deadline = threading.Event()
            for _ in range(100):
                if claim_times.get(job_ok) == t1 and job_lost not in claim_times:
                    break
                deadline.wait(0.01)
        finally:
            stop_event.set()
            thread.join(timeout=2)

    assert not thread.is_alive()
    assert lock_free_during_refresh, "heartbeat refresh was never called"
    assert all(lock_free_during_refresh), "DB refresh ran while claim_times_lock was held"
    # Writeback still applied: refreshed time stored, lost claim removed.
    assert claim_times.get(job_ok) == t1
    assert job_lost not in claim_times
