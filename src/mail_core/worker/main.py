"""Independent worker process — claims jobs with SKIP LOCKED."""

from __future__ import annotations

import logging
import math
import os
import signal
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import NamedTuple

from mail_core.config import get_config
from mail_core.logging_config import configure_logging
from mail_core.providers.connection_slots import TrafficClass, traffic_class_for_job

configure_logging(service_name="mail-core-worker")
log = logging.getLogger("mail_core.worker")

_stop = False
_stop_event = threading.Event()
_wake_event = threading.Event()
CLAIM_HEARTBEAT_MAX_INTERVAL_S = 60.0


@dataclass
class InFlightJob:
    job_id: uuid.UUID
    worker_id: str
    traffic_class: TrafficClass
    locked_at: datetime
    thread: threading.Thread | None = None


_in_flight_jobs: dict[uuid.UUID, InFlightJob] = {}
_in_flight_lock = threading.Lock()


def __getattr__(name: str) -> Any:
    cfg = get_config()
    if name == "RECLAIM_INTERVAL_S":
        return cfg.worker_reclaim_interval_s
    if name == "SCHEDULE_INTERVAL_S":
        return cfg.schedule_interval_s
    if name == "DEFAULT_INBOX_POLL_INTERVAL_S":
        return cfg.inbox_poll_interval_s
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    _stop_event.set()
    _wake_event.set()


def wake() -> None:
    """Wake the worker loop immediately from idle sleep."""
    _wake_event.set()


def request_stop() -> None:
    global _stop
    _stop = True
    _stop_event.set()
    _wake_event.set()


def _wait_for_next_poll(timeout_s: float) -> bool:
    """Interruptible idle wait: returns True as soon as stop is set."""
    _wake_event.wait(timeout_s)
    _wake_event.clear()
    return _stop or _stop_event.is_set()


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


def schedule_periodic_inbox_sync(
    session: Any,
    *,
    poll_interval_s: float | None = None,
    now: Any = None,
    idle_held_account_ids: Any = None,
) -> int:
    """Schedule overdue inbox delta syncs staggered across poll_interval_s (t057 AC-001, AC-002, AC-006, AC-007).

    Accounts currently holding an IDLE seat (t061 AC-005) are skipped:
    IDLE is their discovery channel. They re-enter polling as soon as
    they lose the seat.
    """
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select
    from mail_core.mail.domain.enums import JobStatus, JobType, SyncStatus
    from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint, WorkerJob
    from mail_core.sync.jobs import enqueue_job

    interval = (
        poll_interval_s
        if poll_interval_s is not None
        else get_config().inbox_poll_interval_s
    )
    current_time = now or datetime.now(timezone.utc)

    stmt = (
        select(Folder.id, Folder.account_id)
        .join(Account, Account.id == Folder.account_id)
        .where(
            Account.sync_enabled.is_(True),
            Folder.role == "inbox",
            Folder.sync_status != SyncStatus.PAUSED.value,
        )
        .order_by(Account.id, Folder.id)
    )
    inbox_rows = list(session.execute(stmt).all())
    if not inbox_rows:
        return 0

    held = set(idle_held_account_ids or ())
    overdue: list[tuple[uuid.UUID, uuid.UUID]] = []
    for folder_id, account_id in inbox_rows:
        if account_id in held:
            continue
        dedupe_key = f"delta:{account_id}:{folder_id}"
        in_flight = session.scalar(
            select(WorkerJob.id).where(
                WorkerJob.dedupe_key == dedupe_key,
                WorkerJob.status.in_((JobStatus.PENDING.value, JobStatus.CLAIMED.value)),
            ).limit(1)
        )
        if in_flight is not None:
            continue

        last_synced_at: datetime | None = None
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
        if cp and cp.updated_at:
            last_synced_at = cp.updated_at
        latest_job_finished = session.scalar(
            select(WorkerJob.updated_at)
            .where(
                WorkerJob.dedupe_key == dedupe_key,
                WorkerJob.status.in_((JobStatus.DONE.value, JobStatus.FAILED.value)),
                WorkerJob.updated_at.is_not(None),
            )
            .order_by(WorkerJob.updated_at.desc())
            .limit(1)
        )
        if latest_job_finished and (last_synced_at is None or latest_job_finished > last_synced_at):
            last_synced_at = latest_job_finished

        if last_synced_at is None or (current_time - last_synced_at).total_seconds() >= interval:
            overdue.append((folder_id, account_id))

    if not overdue:
        return 0

    stagger_step = interval / max(len(overdue), 1)
    for idx, (folder_id, account_id) in enumerate(overdue):
        run_after = current_time + timedelta(seconds=idx * stagger_step)
        enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_DELTA.value,
            account_id=account_id,
            payload={"folder_id": str(folder_id)},
            priority=75,
            run_after=run_after,
            dedupe_key=f"delta:{account_id}:{folder_id}",
        )
    return len(overdue)


def _schedule_periodic_sync_once() -> int:
    try:
        from mail_core.db.session import get_session_factory
    except Exception as exc:  # pragma: no cover
        log.error("worker degraded: scheduler imports failed (%s); skipping schedule", exc)
        return 0
    Session = get_session_factory()
    try:
        with Session() as session:
            try:
                from mail_core.sync.idle_watcher import held_idle_account_ids

                enqueued = schedule_periodic_inbox_sync(
                    session, idle_held_account_ids=held_idle_account_ids()
                )
                session.commit()
                if enqueued:
                    log.info("scheduled %s periodic inbox delta sync job(s)", enqueued)
            except Exception:
                session.rollback()
                raise
    except Exception:
        log.exception("periodic inbox scheduler sweep failed")
        enqueued = 0

    # t061: all-folder STATUS patrol sweep (isolated failure domain —
    # a patrol failure must not mask the inbox scheduling above).
    try:
        from mail_core.sync.patrol import schedule_folder_status_patrol

        with Session() as session:
            try:
                patrol_result = schedule_folder_status_patrol(session)
                session.commit()
                if patrol_result.changed:
                    log.info(
                        "patrol probed %s folder(s), %s changed, %s failed",
                        patrol_result.probed,
                        patrol_result.changed,
                        patrol_result.failed,
                    )
            except Exception:
                session.rollback()
                raise
    except Exception:
        log.exception("folder status patrol sweep failed")
    return enqueued


def _claim_heartbeat_interval_s() -> float:
    stale_after_s = _positive_float_setting("MAIL_CORE_RECLAIM_STALE_SECONDS", 300.0)
    return max(0.1, min(CLAIM_HEARTBEAT_MAX_INTERVAL_S, stale_after_s / 3))


class UnifiedClaimHeartbeatLoop:
    """Refreshes claim locked_at for all in-flight jobs across all worker execution threads."""

    def __init__(self, Session, worker_id: str, interval_s: float | None = None) -> None:
        self.Session = Session
        self.worker_id = worker_id
        self.interval_s = interval_s or _claim_heartbeat_interval_s()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="mail-core-unified-claim-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        from mail_core.sync.jobs import heartbeat_job_claim

        while not self._stop_event.wait(self.interval_s):
            with _in_flight_lock:
                snapshot = {
                    jid: t.locked_at for jid, t in _in_flight_jobs.items() if t.locked_at is not None
                }
            if not snapshot:
                continue
            refreshed: dict[uuid.UUID, datetime | None] = {}
            try:
                with self.Session() as session:
                    now = datetime.now(timezone.utc)
                    for jid, expected_locked_at in snapshot.items():
                        refreshed[jid] = heartbeat_job_claim(
                            session,
                            job_id=jid,
                            worker_id=self.worker_id,
                            locked_at=expected_locked_at,
                            now=now,
                        )
                    session.commit()
                with _in_flight_lock:
                    for jid, new_locked_at in refreshed.items():
                        if jid in _in_flight_jobs:
                            if new_locked_at is None:
                                _in_flight_jobs.pop(jid, None)
                            else:
                                _in_flight_jobs[jid].locked_at = new_locked_at
            except Exception as exc:
                from mail_core.security.redact import safe_error

                log.warning("unified claim heartbeat failed: %s", safe_error(exc))


def _execute_single_job(
    Session,
    job_id: uuid.UUID,
    worker_id: str,
    traffic_class: TrafficClass,
) -> bool:
    from mail_core.mail.domain.enums import JobStatus
    from mail_core.mail.storage.models import WorkerJob
    from mail_core.sync.jobs import fail_job
    from mail_core.worker.handlers import handle_job

    ok = False
    try:
        with Session() as session:
            job = session.get(WorkerJob, job_id)
            if job is None or job.status != JobStatus.CLAIMED.value or job.locked_by != worker_id:
                return False
            try:
                ok = handle_job(session, job, worker_id=worker_id)
                if session.in_transaction():
                    session.commit()
            except Exception as exc:
                from mail_core.security.redact import safe_error

                log.error("job %s failed: %s", job_id, safe_error(exc))
                try:
                    session.rollback()
                except Exception:
                    pass
                try:
                    with Session() as fail_session:
                        j = fail_session.get(WorkerJob, job_id)
                        if j is not None and j.status == JobStatus.CLAIMED.value:
                            fail_job(fail_session, j, exc, worker_id=worker_id)
                            fail_session.commit()
                except Exception:
                    log.exception("fail_job after error also failed for %s", job_id)
    finally:
        with _in_flight_lock:
            _in_flight_jobs.pop(job_id, None)
        wake()
    return ok


def _tick(worker_id: str, *, block: bool = True, limit: int | None = None) -> TickResult:
    """Claim and execute jobs concurrently respecting total_slots and traffic class limits."""
    cfg = get_config()
    total_slots = cfg.total_slots
    background_start_slot = cfg.background_start_slot
    background_limit = total_slots - background_start_slot

    try:
        from mail_core.db.session import get_session_factory
        from mail_core.sync.jobs import claim_jobs
    except Exception as exc:  # pragma: no cover
        log.error("worker degraded: tick imports failed (%s); skipping claim", exc)
        return TickResult(claimed=0, handled=0)

    Session = get_session_factory()

    with _in_flight_lock:
        dead = [jid for jid, t in _in_flight_jobs.items() if t.thread and not t.thread.is_alive()]
        for jid in dead:
            _in_flight_jobs.pop(jid, None)
        current_in_flight = len(_in_flight_jobs)
        bg_in_flight = sum(
            1 for t in _in_flight_jobs.values() if t.traffic_class == TrafficClass.BACKGROUND
        )

    free_slots = max(0, total_slots - current_in_flight)
    if limit is not None:
        free_slots = min(free_slots, limit)

    if free_slots <= 0:
        return TickResult(claimed=0, handled=0)

    claimed_jobs = []
    while free_slots > 0:
        bg_total = bg_in_flight + sum(1 for _, tc, _ in claimed_jobs if tc == TrafficClass.BACKGROUND)
        allow_bg = bg_total < background_limit

        with Session() as session:
            jobs = claim_jobs(
                session,
                worker_id=worker_id,
                limit=1,
                exclude_background=not allow_bg,
                exclude_busy_lease_accounts=True,
            )
            if not jobs:
                break
            job = jobs[0]
            tc = traffic_class_for_job(job.job_type, payload=job.payload)
            claimed_jobs.append((job.id, tc, job.locked_at))
            session.commit()
        free_slots -= 1

    if not claimed_jobs:
        return TickResult(claimed=0, handled=0)

    threads = []
    handled_count = 0
    handled_lock = threading.Lock()

    for jid, tc, locked_at in claimed_jobs:
        token = InFlightJob(job_id=jid, worker_id=worker_id, traffic_class=tc, locked_at=locked_at)
        with _in_flight_lock:
            _in_flight_jobs[jid] = token

        def _task(job_id=jid, t_class=tc):
            nonlocal handled_count
            ok = _execute_single_job(Session, job_id, worker_id, t_class)
            if ok:
                with handled_lock:
                    handled_count += 1

        t = threading.Thread(target=_task, name=f"worker-task-{jid.hex[:8]}", daemon=True)
        token.thread = t
        threads.append(t)
        t.start()

    if block:
        for t in threads:
            t.join()

    return TickResult(claimed=len(claimed_jobs), handled=handled_count if block else len(claimed_jobs))


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
    _stop_event.clear()
    _wake_event.clear()
    from mail_core.blobs.crypto import load_keyring_from_env

    # Fail fast: worker must not process jobs without blob keys.
    load_keyring_from_env()

    cfg = get_config()
    interval = (
        poll_interval_s
        if poll_interval_s is not None
        else cfg.worker_poll_s
    )
    worker_id = cfg.worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGINT, _handle_stop)
        signal.signal(signal.SIGTERM, _handle_stop)
    max_idle = cfg.worker_max_idle_s
    heartbeat_interval = cfg.worker_heartbeat_s
    reclaim_interval = cfg.worker_reclaim_interval_s
    schedule_interval = cfg.schedule_interval_s
    log.info("worker %s starting (poll=%ss, max_idle=%ss)", worker_id, interval, max_idle)
    sleep_s = interval
    last_reclaim_at: float | None = None
    last_schedule_at: float | None = None

    from mail_core.db.session import get_session_factory
    from mail_core.worker.heartbeat import WorkerHeartbeatLoop

    Session = get_session_factory()
    heartbeat_loop = WorkerHeartbeatLoop(worker_id, Session, interval_s=heartbeat_interval)
    heartbeat_loop.start()

    claim_heartbeat = UnifiedClaimHeartbeatLoop(Session, worker_id)
    claim_heartbeat.start()

    job_listener = None
    try:
        from mail_core.worker.wake import JobWakeListener

        job_listener = JobWakeListener(wake)
        job_listener.start()
        log.info("job wake listener started")
    except Exception:
        log.exception("job wake listener failed to start; polling remains authoritative")

    # t061: IDLE watcher runs inside the worker process; a watcher
    # failure must never take the worker down (polling remains the
    # authoritative discovery path).
    idle_manager = None
    try:
        from mail_core.sync.idle_watcher import get_idle_manager

        idle_manager = get_idle_manager(Session)
        idle_manager.start()
        log.info("idle watcher started (quota from central config)")
    except Exception:
        log.exception("idle watcher failed to start; polling remains authoritative")

    try:
        while not _stop and not _stop_event.is_set():
            now = time.monotonic()
            if last_reclaim_at is None or now - last_reclaim_at >= reclaim_interval:
                last_reclaim_at = now
                try:
                    _reclaim_once()
                except Exception as exc:  # pragma: no cover
                    from mail_core.security.redact import safe_error

                    log.error("reclaim sweep failed: %s", safe_error(exc))

            if last_schedule_at is None or now - last_schedule_at >= schedule_interval:
                last_schedule_at = now
                try:
                    # AC-009: run periodic schedule / patrol sweeps asynchronously
                    # so network probing never blocks task claiming.
                    threading.Thread(
                        target=_schedule_periodic_sync_once,
                        name="worker-periodic-schedule",
                        daemon=True,
                    ).start()
                except Exception as exc:  # pragma: no cover
                    from mail_core.security.redact import safe_error

                    log.error("periodic schedule sweep failed: %s", safe_error(exc))

            tick_result = TickResult(claimed=0, handled=0)
            try:
                tick_result = _tick(worker_id, block=False)
                if tick_result.claimed:
                    log.info("claimed %s job(s)", tick_result.claimed)
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
                _wait_for_next_poll(sleep_s)
    finally:
        # AC-010: Graceful shutdown: wait for in-flight tasks to complete within timeout
        shutdown_deadline = time.monotonic() + 5.0
        while time.monotonic() < shutdown_deadline:
            with _in_flight_lock:
                dead = [jid for jid, t in _in_flight_jobs.items() if t.thread and not t.thread.is_alive()]
                for jid in dead:
                    _in_flight_jobs.pop(jid, None)
                if not _in_flight_jobs:
                    break
            time.sleep(0.05)

        claim_heartbeat.stop(timeout=5.0)

        if job_listener is not None:
            try:
                job_listener.stop(timeout=5.0)
            except Exception:
                log.exception("job wake listener stop failed")
        if idle_manager is not None:
            try:
                idle_manager.stop()
            except Exception:
                log.exception("idle watcher stop failed")
        heartbeat_loop.stop(timeout=5.0)
    log.info("worker loop stopped")


if __name__ == "__main__":
    run()
