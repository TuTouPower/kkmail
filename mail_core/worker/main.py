"""Independent worker process — claims jobs with SKIP LOCKED."""

from __future__ import annotations

import logging
import os
import signal
import threading
import time
import uuid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [mail-core-worker] %(message)s")
log = logging.getLogger("mail_core.worker")

_stop = False
CLAIM_BATCH = 5


def _handle_stop(signum: int, _frame: object) -> None:
    global _stop
    log.info("received signal %s; stopping", signum)
    _stop = True


def request_stop() -> None:
    global _stop
    _stop = True


def _reclaim_once() -> int:
    """Periodically reclaim stuck claims and prune old dispatched outbox rows."""
    try:
        from datetime import timedelta

        from mail_core.blobs.archive import reclaim_stale_archive_claims
        from mail_core.db.session import get_session_factory
        from mail_core.realtime.outbox import prune_dispatched
        from mail_core.sync.jobs import reclaim_stale_claims
    except Exception as exc:  # pragma: no cover
        log.error("worker degraded: reclaim imports failed (%s); skipping reclaim", exc)
        return 0

    Session = get_session_factory()
    with Session() as session:
        try:
            n = reclaim_stale_claims(session, older_than=timedelta(minutes=5), limit=100)
            if n:
                log.info("reclaimed %s stale CLAIMED job(s)", n)
            a = reclaim_stale_archive_claims(session, older_than=timedelta(minutes=15), limit=100)
            if a:
                log.info("reclaimed %s stale archive_in_progress claim(s)", a)
            pruned = prune_dispatched(session, older_than=timedelta(days=7), limit=2000)
            if pruned:
                log.info("pruned %s dispatched outbox row(s)", pruned)
            session.commit()
            return n + a + pruned
        except Exception:
            session.rollback()
            log.exception("reclaim_stale_claims failed")
            return 0


def _tick(worker_id: str) -> int:
    """Claim a batch, commit claims, then handle each job in its own session.

    One job per session avoids a failed job rolling back siblings and keeps
    network-heavy handlers from holding a multi-job transaction open.
    """
    try:
        from mail_core.db.session import get_session_factory
        from mail_core.mail.domain.enums import JobStatus
        from mail_core.mail.storage.models import WorkerJob
        from mail_core.sync.jobs import claim_jobs, fail_job
        from mail_core.worker.handlers import handle_job
    except Exception as exc:  # pragma: no cover
        log.error("worker degraded: tick imports failed (%s); skipping claim batch", exc)
        return 0

    _reclaim_once()

    Session = get_session_factory()
    claim_tokens: list[tuple] = []
    with Session() as session:
        jobs = claim_jobs(session, worker_id=worker_id, limit=CLAIM_BATCH)
        claim_tokens = [(j.id, j.locked_by, j.locked_at) for j in jobs]
        session.commit()

    handled = 0
    for job_id, expected_owner, claim_time in claim_tokens:
        with Session() as session:
            job = session.get(WorkerJob, job_id)
            if job is None:
                continue
            if expected_owner is not None:
                if job.status != JobStatus.CLAIMED.value or job.locked_by != expected_owner:
                    log.warning(
                        "job %s claim lost before execution (status=%s, locked_by=%s, expected=%s); skipping",
                        job_id,
                        job.status,
                        job.locked_by,
                        expected_owner,
                    )
                    continue
                if claim_time is not None and job.locked_at is not None and job.locked_at != claim_time:
                    log.warning(
                        "job %s claim lock timestamp mismatch (%s != %s); skipping",
                        job_id,
                        job.locked_at,
                        claim_time,
                    )
                    continue
            try:
                ok = handle_job(session, job, worker_id=worker_id)
                # Handlers may have committed already; commit any leftover work
                # (including fail_job flushes when ok is False).
                if session.in_transaction():
                    session.commit()
                if ok:
                    handled += 1
            except Exception as exc:  # pragma: no cover
                from mail_core.security.redact import safe_error

                log.error("job %s failed: %s", job_id, safe_error(exc))
                try:
                    session.rollback()
                except Exception:
                    pass
                try:
                    # Re-load after rollback so fail_job can persist.
                    # Skip if handle_job already marked FAILED (avoid double-handle).
                    from mail_core.mail.domain.enums import JobStatus

                    job = session.get(WorkerJob, job_id)
                    if job is not None and job.status == JobStatus.CLAIMED.value:
                        fail_job(session, job, exc, worker_id=worker_id)
                        session.commit()
                except Exception:
                    session.rollback()
                    log.exception("fail_job after error also failed for %s", job_id)
    return handled


def next_poll_delay(handled: int, previous: float, *, base: float, max_idle: float) -> float:
    """Deep queue (full batch) → poll again immediately; idle → exponential back-off."""
    if handled >= CLAIM_BATCH:
        return 0.0
    if handled > 0:
        return base
    return min(max_idle, max(base, previous * 2 if previous else base))


def run(poll_interval_s: float | None = None) -> None:
    global _stop
    _stop = False
    from mail_core.blobs.crypto import load_keyring_from_env

    # Fail fast: worker must not process jobs without blob keys.
    load_keyring_from_env()

    interval = poll_interval_s if poll_interval_s is not None else float(os.environ.get("MAIL_CORE_WORKER_POLL_S", "2"))
    worker_id = os.environ.get("MAIL_CORE_WORKER_ID") or f"worker-{uuid.uuid4().hex[:8]}"
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _handle_stop)
        signal.signal(signal.SIGTERM, _handle_stop)
    max_idle = float(os.environ.get("MAIL_CORE_WORKER_MAX_IDLE_S") or max(interval, 10.0))
    log.info("worker %s starting (poll=%ss, max_idle=%ss)", worker_id, interval, max_idle)
    sleep_s = interval
    while not _stop:
        n = 0
        try:
            n = _tick(worker_id)
            if n:
                log.info("handled %s job(s)", n)
        except Exception as exc:
            from mail_core.security.redact import safe_error

            log.error("tick failed: %s", safe_error(exc))
        sleep_s = next_poll_delay(n, sleep_s, base=interval, max_idle=max_idle)
        if sleep_s:
            time.sleep(sleep_s)
    log.info("worker loop stopped")


if __name__ == "__main__":
    run()
