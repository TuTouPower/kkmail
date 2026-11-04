"""A297: claim heartbeat DB refresh must not hold the in-flight lock across IO."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from mail_core.worker import main as worker_main


def test_heartbeat_db_refresh_runs_outside_claim_times_lock():
    job_ok, job_lost = uuid.uuid4(), uuid.uuid4()
    t0 = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 10, 25, 10, 1, tzinfo=timezone.utc)
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
        # If the heartbeat thread still held the in-flight lock across this
        # DB call, concurrent claim/tick bookkeeping would be blocked; probe it.
        acquired = worker_main._in_flight_lock.acquire(timeout=0.5)
        lock_free_during_refresh.append(acquired)
        if acquired:
            worker_main._in_flight_lock.release()
        refreshed_once.set()
        return t1 if job_id == job_ok else None

    tokens = {
        job_id: worker_main.InFlightJob(
            job_id=job_id,
            worker_id="worker-1",
            traffic_class=worker_main.TrafficClass.FOREGROUND,
            locked_at=t0,
        )
        for job_id in (job_ok, job_lost)
    }
    with worker_main._in_flight_lock:
        worker_main._in_flight_jobs.update(tokens)

    loop = worker_main.UnifiedClaimHeartbeatLoop(
        lambda: Session(), "worker-1", interval_s=0.01
    )
    ok_locked_at = None
    lost_present = True
    try:
        with patch("mail_core.sync.jobs.heartbeat_job_claim", side_effect=refresh):
            loop.start()
            assert refreshed_once.wait(timeout=2)
            # Let the writeback phase complete before stopping.
            deadline = threading.Event()
            for _ in range(200):
                with worker_main._in_flight_lock:
                    ok_locked_at = worker_main._in_flight_jobs[job_ok].locked_at
                    lost_present = job_lost in worker_main._in_flight_jobs
                if ok_locked_at == t1 and not lost_present:
                    break
                deadline.wait(0.01)
    finally:
        loop.stop(timeout=2)
        with worker_main._in_flight_lock:
            for job_id in (job_ok, job_lost):
                worker_main._in_flight_jobs.pop(job_id, None)

    assert not loop._thread.is_alive()
    assert lock_free_during_refresh, "heartbeat refresh was never called"
    assert all(lock_free_during_refresh), "DB refresh ran while the in-flight lock was held"
    # Writeback still applied: refreshed time stored, lost claim removed.
    assert ok_locked_at == t1
    assert lost_present is False
