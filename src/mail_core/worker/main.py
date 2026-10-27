"""Independent worker process — claims jobs with SKIP LOCKED."""

from __future__ import annotations

import logging
import math
import os
import signal
import threading
import time
import uuid
from typing import NamedTuple

from mail_core.logging_config import configure_logging

configure_logging(service_name="mail-core-worker")
log = logging.getLogger("mail_core.worker")

_stop = False
CLAIM_BATCH = 5
RECLAIM_INTERVAL_S = 60.0
CLAIM_HEARTBEAT_MAX_INTERVAL_S = 60.0


def _positive_float_setting(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        value = None
    if value is None or not math.isfinite(value) or value <= 0:
        log.warning("invalid numeric environment setting %s=%r; using default %s", name, raw, default)
        return default
    return value


class TickResult(NamedTuple):
    claimed: int
    handled: int


def _handle_stop(signum: int, _frame: object) -> None:
    global _stop
    log.info("received signal %s; stopping", signum)
    _stop = True


def request_stop() -> None:
    global _stop
    _stop = True


def _reclaim_once() -> int:
    """Periodically reclaim stuck claims and prune expired published outbox rows.

    A68: each sweep runs in its own session/transaction. A failure in one
    sweep is logged and counted as zero for that sweep only; it must not roll
    back or skip the remaining sweeps for the next RECLAIM_INTERVAL_S.
    """
    try:
        from datetime import timedelta

        from mail_core.blobs.archive import maybe_resume_quota_paused_archives, reclaim_stale_archive_claims
        from mail_core.blobs.quota import prune_expired_quota_reservations
        from mail_core.db.session import get_session_factory
        from mail_core.realtime.outbox import prune_published
        from mail_core.sync.execution import converge_orphaned_bindings
        from mail_core.sync.jobs import prune_completed_jobs, reclaim_stale_claims
        from mail_core.worker.heartbeat import cleanup_stale_heartbeats
    except Exception as exc:  # pragma: no cover
        log.error("worker degraded: reclaim imports failed (%s); skipping reclaim", exc)
        return 0

    Session = get_session_factory()
    reclaim_sec = _positive_float_setting("MAIL_CORE_RECLAIM_STALE_SECONDS", 300.0)
    # (name, sweep, log message, counted in the return total). The counted
    # subset preserves the historical return-value composition.
    sweeps = [
        (
            "reclaim_stale_claims",
            lambda s: reclaim_stale_claims(s, older_than=timedelta(seconds=reclaim_sec), limit=100),
            "reclaimed %s stale CLAIMED job(s)",
            True,
        ),
        (
            "reclaim_stale_archive_claims",
            lambda s: reclaim_stale_archive_claims(s, older_than=timedelta(minutes=15), limit=100),
            "reclaimed %s stale archive_in_progress claim(s)",
            True,
        ),
        (
            "prune_published",
            lambda s: prune_published(s, older_than=timedelta(days=7), limit=5000),
            "pruned %s published outbox row(s)",
            True,
        ),
        (
            "prune_completed_jobs",
            lambda s: prune_completed_jobs(s, older_than=timedelta(days=7), limit=1000),
            "pruned %s completed/failed worker job(s)",
            True,
        ),
        (
            "converge_orphaned_bindings",
            lambda s: converge_orphaned_bindings(s, limit=200),
            "converged %s orphaned sync-request binding(s)",
            False,
        ),
        (
            "prune_expired_quota_reservations",
            lambda s: prune_expired_quota_reservations(s),
            "pruned %s expired blob quota reservation(s)",
            False,
        ),
        (
            "maybe_resume_quota_paused_archives",
            lambda s: maybe_resume_quota_paused_archives(s, limit=100),
            "resumed %s quota paused archive(s)",
            False,
        ),
        (
            "cleanup_stale_heartbeats",
            lambda s: cleanup_stale_heartbeats(s),
            "cleaned %s expired worker heartbeat(s)",
            True,
        ),
    ]
    total = 0
    for name, sweep, message, counted in sweeps:
        try:
            with Session() as session:
                try:
                    value = sweep(session) or 0
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
        except Exception:
            log.exception("reclaim sweep %s failed", name)
            continue
        if value:
            log.info(message, value)
        if counted:
            total += value
    return total


def _claim_heartbeat_interval_s() -> float:
    stale_after_s = _positive_float_setting("MAIL_CORE_RECLAIM_STALE_SECONDS", 300.0)
    return max(0.1, min(CLAIM_HEARTBEAT_MAX_INTERVAL_S, stale_after_s / 3))


def _heartbeat_claims(Session, claim_tokens, claim_times, claim_times_lock, stop_event) -> None:
    """Refresh every outstanding claim, including jobs waiting in this tick's batch."""
    from datetime import datetime, timezone

    from mail_core.sync.jobs import heartbeat_job_claim

    active = {
        job_id: owner
        for job_id, owner, locked_at in claim_tokens
        if owner is not None and locked_at is not None
    }
    while active and not stop_event.wait(_claim_heartbeat_interval_s()):
        refreshed: dict[object, datetime | None] = {}
        try:
            # A297: snapshot claim_times under the lock, run the DB refresh
            # (IO + commit) outside it, then write results back in a short
            # critical section — the lock must not span IO or it blocks the
            # main thread's per-job claim validation in _tick.
            with claim_times_lock:
                snapshot = {job_id: claim_times.get(job_id) for job_id in list(active)}
            with Session() as session:
                now = datetime.now(timezone.utc)
                for job_id, owner in list(active.items()):
                    expected_locked_at = snapshot.get(job_id)
                    if expected_locked_at is None:
                        refreshed[job_id] = None
                        continue
                    refreshed[job_id] = heartbeat_job_claim(
                        session,
                        job_id=job_id,
                        worker_id=owner,
                        locked_at=expected_locked_at,
                        now=now,
                    )
                session.commit()
            with claim_times_lock:
                for job_id, locked_at in refreshed.items():
                    if locked_at is None:
                        active.pop(job_id, None)
                        claim_times.pop(job_id, None)
                    else:
                        claim_times[job_id] = locked_at
        except Exception as exc:
            from mail_core.security.redact import safe_error

            log.warning("worker job claim heartbeat failed: %s", safe_error(exc))


def _tick(worker_id: str) -> TickResult:
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
        return TickResult(claimed=0, handled=0)

    Session = get_session_factory()
    claim_tokens: list[tuple] = []
    with Session() as session:
        jobs = claim_jobs(session, worker_id=worker_id, limit=CLAIM_BATCH)
        claim_tokens = [(j.id, j.locked_by, j.locked_at) for j in jobs]
        session.commit()

    claim_times = {job_id: locked_at for job_id, _owner, locked_at in claim_tokens}
    claim_times_lock = threading.Lock()
    heartbeat_stop = threading.Event()
    heartbeat_tokens = [token for token in claim_tokens if token[1] is not None and token[2] is not None]
    heartbeat_thread = None
    if heartbeat_tokens:
        heartbeat_thread = threading.Thread(
            target=_heartbeat_claims,
            args=(Session, heartbeat_tokens, claim_times, claim_times_lock, heartbeat_stop),
            name="mail-core-job-claim-heartbeat",
            daemon=True,
        )
        heartbeat_thread.start()

    handled = 0
    try:
        for job_id, expected_owner, _claim_time in claim_tokens:
            with Session() as session:
                with claim_times_lock:
                    claim_time = claim_times.get(job_id)
                    claim_tracked = job_id in claim_times
                    job = session.get(WorkerJob, job_id)
                    if job is None:
                        continue
                    if expected_owner is not None:
                        if not claim_tracked or job.status != JobStatus.CLAIMED.value or job.locked_by != expected_owner:
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
    finally:
        heartbeat_stop.set()
        if heartbeat_thread is not None:
            heartbeat_thread.join(timeout=5.0)
    return TickResult(claimed=len(claim_tokens), handled=handled)


def next_poll_delay(
    handled: int,
    previous: float,
    *,
    base: float,
    max_idle: float,
    claimed: int = 0,
) -> float:
    """Poll at the base interval after work; back off only after empty claims."""
    if claimed > 0 or handled > 0:
        return base
    return min(max_idle, max(base, previous * 2 if previous else base))


def run(poll_interval_s: float | None = None) -> None:
    global _stop
    _stop = False
    from mail_core.blobs.crypto import load_keyring_from_env

    # Fail fast: worker must not process jobs without blob keys.
    load_keyring_from_env()

    interval = (
        poll_interval_s
        if poll_interval_s is not None
        else _positive_float_setting("MAIL_CORE_WORKER_POLL_S", 2.0)
    )
    worker_id = os.environ.get("MAIL_CORE_WORKER_ID") or f"worker-{uuid.uuid4().hex[:8]}"
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _handle_stop)
        signal.signal(signal.SIGTERM, _handle_stop)
    max_idle = _positive_float_setting("MAIL_CORE_WORKER_MAX_IDLE_S", max(interval, 10.0))
    heartbeat_interval = _positive_float_setting("MAIL_CORE_WORKER_HEARTBEAT_S", 15.0)
    log.info("worker %s starting (poll=%ss, max_idle=%ss)", worker_id, interval, max_idle)
    sleep_s = interval
    last_reclaim_at: float | None = None

    from mail_core.db.session import get_session_factory
    from mail_core.worker.heartbeat import WorkerHeartbeatLoop

    Session = get_session_factory()
    heartbeat_loop = WorkerHeartbeatLoop(worker_id, Session, interval_s=heartbeat_interval)
    heartbeat_loop.start()

    try:
        while not _stop:
            now = time.monotonic()
            if last_reclaim_at is None or now - last_reclaim_at >= RECLAIM_INTERVAL_S:
                last_reclaim_at = now
                try:
                    _reclaim_once()
                except Exception as exc:  # pragma: no cover
                    from mail_core.security.redact import safe_error

                    log.error("reclaim sweep failed: %s", safe_error(exc))

            tick_result = TickResult(claimed=0, handled=0)
            try:
                tick_result = _tick(worker_id)
                if tick_result.handled:
                    log.info("handled %s job(s)", tick_result.handled)
            except Exception as exc:
                from mail_core.security.redact import safe_error

                log.error("tick failed: %s", safe_error(exc))
            sleep_s = next_poll_delay(
                tick_result.handled,
                sleep_s,
                base=interval,
                max_idle=max_idle,
                claimed=tick_result.claimed,
            )
            if sleep_s:
                time.sleep(sleep_s)
    finally:
        heartbeat_loop.stop(timeout=5.0)
    log.info("worker loop stopped")


if __name__ == "__main__":
    run()
