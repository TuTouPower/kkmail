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


def _handle_stop(signum: int, _frame: object) -> None:
    global _stop
    log.info("received signal %s; stopping", signum)
    _stop = True


def request_stop() -> None:
    global _stop
    _stop = True


def _tick(worker_id: str) -> int:
    """Claim and handle one batch. Returns number of jobs handled. No-op if DB down."""
    try:
        from datetime import timedelta

        from mail_core.db.session import get_session_factory
        from mail_core.sync.jobs import claim_jobs, reclaim_stale_claims
        from mail_core.worker.handlers import handle_job
    except Exception as exc:  # pragma: no cover
        log.warning("worker imports failed: %s", exc)
        return 0

    Session = get_session_factory()
    handled = 0
    with Session() as session:
        try:
            n = reclaim_stale_claims(session, older_than=timedelta(minutes=5), limit=100)
            if n:
                log.info("reclaimed %s stale CLAIMED job(s)", n)
            session.commit()
        except Exception:
            session.rollback()
            log.exception("reclaim_stale_claims failed")
    with Session() as session:
        jobs = claim_jobs(session, worker_id=worker_id, limit=CLAIM_BATCH)
        for job in jobs:
            try:
                handle_job(session, job)
                handled += 1
            except Exception as exc:  # pragma: no cover
                from mail_core.security.redact import safe_error
                from mail_core.sync.jobs import fail_job

                log.error("job %s failed: %s", job.id, safe_error(exc))
                fail_job(session, job, exc)
        session.commit()
    return handled


CLAIM_BATCH = 5


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
