"""Independent worker process — claims jobs with SKIP LOCKED."""

from __future__ import annotations

import logging
import math
import os
import signal
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, NamedTuple

from mail_core.config import get_config
from mail_core.logging_config import configure_logging
from mail_core.providers.connection_slots import TrafficClass, traffic_class_for_job

configure_logging(service_name="mail-core-worker")
log = logging.getLogger("mail_core.worker")

_stop = False
_stop_event = threading.Event()
_wake_event = threading.Event()
CLAIM_HEARTBEAT_MAX_INTERVAL_S = 60.0
LIVENESS_WARN_INTERVAL_S = 60.0
_CFG_UNREACHABLE_PROBE_CLAIMED_AT = "unreachable_probe_claimed_at"
UNREACHABLE_PROBE_LEASE_S = 120.0


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
        from mail_core.sync.execution import converge_stalled_targets
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
            lambda s: prune_published(s),
            "pruned %s published outbox row(s)",
            True,
        ),
        (
            "prune_completed_jobs",
            lambda s: prune_completed_jobs(s),
            "pruned %s completed/failed worker job(s)",
            True,
        ),
        (
            "converge_stalled_targets",
            lambda s: converge_stalled_targets(s, limit=200),
            "converged %s stalled sync-request target(s)",
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
    from mail_core.mail.domain.enums import ExecutionOrigin, JobStatus, JobType
    from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint, WorkerJob, syncable_folder_clauses
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
            *syncable_folder_clauses(),
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

        # t094 AC-002: the checkpoint is the single authoritative watermark.
        # Three-state first-scheduling contract:
        #   * no checkpoint / full_scan_complete=False -> NOT delta-eligible;
        #     the metadata discovery chain owns establishing the baseline.
        #     Scheduling a delta here spins on baseline_required/pending with
        #     nowhere to record a settlement.
        #   * baseline ready, last_delta_settled_at NULL -> due now (first pass).
        #   * baseline ready, watermark set -> due when the interval elapsed.
        # NOTE: ``scan_generation`` is NOT a "rebuilding" flag — it persists
        # after a tracked full scan completes; rebuilding is expressed by
        # ``full_scan_complete=False`` (set by begin_scan_generation and
        # invalidate_checkpoint_for_rebuild). Do not gate on it here.
        cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
        if cp is None or not cp.full_scan_complete:
            continue
        last_synced_at = cp.last_delta_settled_at

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
            execution_origin=ExecutionOrigin.BACKGROUND,
            account_id=account_id,
            payload={"folder_id": str(folder_id)},
            priority=75,
            run_after=run_after,
            dedupe_key=f"delta:{account_id}:{folder_id}",
        )
    return len(overdue)


@dataclass(frozen=True, slots=True)
class _UnreachableProbeCandidate:
    account_snapshot: Any
    inbox_remote_id: str | None


def _parse_utc_timestamp(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _default_unreachable_probe_provider(account: Any) -> Any:
    from mail_core.providers.factory import build_provider

    return build_provider(account, traffic_class=TrafficClass.BACKGROUND)


def _select_overdue_unreachable_candidates(
    session: Any,
    *,
    now: datetime,
) -> list[_UnreachableProbeCandidate]:
    from sqlalchemy import select
    from mail_core.accounts.health import UNREACHABLE_RECHECK_INTERVAL, _stored_failure_timestamps
    from mail_core.mail.domain.enums import ConnectivityState, FolderRole
    from mail_core.mail.storage.models import Account, Folder, syncable_folder_clauses

    accounts = list(
        session.scalars(
            select(Account)
            .where(
                Account.sync_enabled.is_(True),
                Account.connectivity_state == ConnectivityState.UNREACHABLE.value,
            )
            .order_by(Account.id)
        ).all()
    )
    if not accounts:
        return []

    overdue_accounts: list[Account] = []
    for acc in accounts:
        cfg = dict(acc.config or {})
        stamps = _stored_failure_timestamps(cfg)
        if not stamps or (now - max(stamps)) >= UNREACHABLE_RECHECK_INTERVAL:
            overdue_accounts.append(acc)
    if not overdue_accounts:
        return []

    account_ids = [acc.id for acc in overdue_accounts]
    inbox_rows = session.execute(
        select(Folder.account_id, Folder.remote_id)
        .where(
            Folder.account_id.in_(account_ids),
            Folder.role == FolderRole.INBOX.value,
            *syncable_folder_clauses(),
        )
        .order_by(Folder.account_id, Folder.created_at.asc(), Folder.id.asc())
    ).all()
    inbox_by_account: dict[uuid.UUID, str] = {}
    for aid, remote_id in inbox_rows:
        inbox_by_account.setdefault(aid, remote_id)

    return [
        _UnreachableProbeCandidate(
            account_snapshot=Account(
                id=acc.id,
                email=acc.email,
                provider=acc.provider,
                credential_ref=acc.credential_ref,
                config=dict(acc.config or {}),
            ),
            inbox_remote_id=inbox_by_account.get(acc.id),
        )
        for acc in overdue_accounts
    ]


def _claim_unreachable_probe_lease(
    session: Any,
    *,
    account_id: uuid.UUID,
    now: datetime,
    lease_s: float = UNREACHABLE_PROBE_LEASE_S,
) -> bool:
    from sqlalchemy import select, text
    from mail_core.accounts.health import UNREACHABLE_RECHECK_INTERVAL, _stored_failure_timestamps
    from mail_core.mail.domain.enums import ConnectivityState
    from mail_core.mail.storage.models import Account

    row = session.execute(
        select(Account.id, Account.config)
        .where(
            Account.id == account_id,
            Account.sync_enabled.is_(True),
            Account.connectivity_state == ConnectivityState.UNREACHABLE.value,
        )
        .with_for_update(skip_locked=True)
    ).first()
    if row is None:
        return False
    cfg = dict(row[1] or {})
    stamps = _stored_failure_timestamps(cfg)
    if stamps and (now - max(stamps)) < UNREACHABLE_RECHECK_INTERVAL:
        return False
    claimed_at = _parse_utc_timestamp(cfg.get(_CFG_UNREACHABLE_PROBE_CLAIMED_AT))
    if claimed_at is not None and (now - claimed_at).total_seconds() < lease_s:
        return False
    session.execute(
        text(
            """
            UPDATE accounts
            SET config = COALESCE(config, '{}'::jsonb)
                || jsonb_build_object(CAST(:claim_key AS text), CAST(:claim_value AS text))
            WHERE id = :account_id
            """
        ),
        {
            "claim_key": _CFG_UNREACHABLE_PROBE_CLAIMED_AT,
            "claim_value": now.isoformat(),
            "account_id": account_id,
        },
    )
    return True


def _probe_account_reachability(
    candidate: _UnreachableProbeCandidate,
    *,
    provider_factory: Any,
) -> None:
    provider = provider_factory(candidate.account_snapshot)
    if candidate.inbox_remote_id:
        status = provider.probe_folder_status(candidate.inbox_remote_id)
        if status is not None:
            return
    list_folders = getattr(provider, "list_folders", None)
    if callable(list_folders):
        list_folders()
        return
    discover_folders = getattr(provider, "discover_folders", None)
    if callable(discover_folders):
        discover_folders()
        return
    raise RuntimeError("provider supports neither probe_folder_status nor folder discovery")


def _settle_unreachable_probe_result(
    session: Any,
    *,
    account_id: uuid.UUID,
    probe_exc: Exception | None,
    now: datetime,
) -> None:
    from sqlalchemy import delete, func, select
    from mail_core.accounts.health import (
        mark_credential_invalid,
        record_connectivity_failure,
        record_connectivity_success,
    )
    from mail_core.mail.domain.enums import (
        ConnectivityState,
        ExecutionOrigin,
        FolderRole,
        JobStatus,
        JobType,
        OutboxEventType,
    )
    from mail_core.mail.domain.failures import FailureDomain
    from mail_core.mail.storage.models import (
        Account,
        Folder,
        OutboxEvent,
        SyncCheckpoint,
        WorkerJob,
        syncable_folder_clauses,
    )
    from mail_core.sync.context import classify_failure
    from mail_core.sync.jobs import enqueue_job

    acc = session.scalar(
        select(Account).where(Account.id == account_id).with_for_update()
    )
    if acc is None:
        return
    if isinstance(acc.config, dict) and _CFG_UNREACHABLE_PROBE_CLAIMED_AT in acc.config:
        cleaned_cfg = dict(acc.config)
        cleaned_cfg.pop(_CFG_UNREACHABLE_PROBE_CLAIMED_AT, None)
        acc.config = cleaned_cfg

    if acc.connectivity_state != ConnectivityState.UNREACHABLE.value or not acc.sync_enabled:
        session.flush()
        return

    if probe_exc is None:
        record_connectivity_success(session, account_id, now=now)
        has_inbox_baseline = session.scalar(
            select(SyncCheckpoint.folder_id)
            .join(Folder, Folder.id == SyncCheckpoint.folder_id)
            .where(
                SyncCheckpoint.account_id == account_id,
                Folder.account_id == account_id,
                Folder.role == FolderRole.INBOX.value,
                *syncable_folder_clauses(),
                SyncCheckpoint.full_scan_complete.is_(True),
            )
            .limit(1)
        )
        if has_inbox_baseline is None:
            active_discovery = session.scalar(
                select(WorkerJob.id)
                .where(
                    WorkerJob.account_id == account_id,
                    WorkerJob.job_type == JobType.SYNC_ACCOUNT_FOLDERS.value,
                    WorkerJob.status.in_((JobStatus.PENDING.value, JobStatus.CLAIMED.value)),
                )
                .limit(1)
            )
            if active_discovery is None:
                enqueue_job(
                    session,
                    job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
                    execution_origin=ExecutionOrigin.FOREGROUND,
                    account_id=account_id,
                    payload={},
                    priority=50,
                    dedupe_key=f"sync-folders:{account_id}",
                )
        return

    if classify_failure(probe_exc).domain == FailureDomain.AUTH:
        mark_credential_invalid(session, account_id)
        return

    max_existing_outbox_id = session.scalar(select(func.max(OutboxEvent.id))) or 0
    record_connectivity_failure(session, account_id, error=probe_exc, now=now)
    # Failed half-open probe must keep the breaker UNREACHABLE (not empty-demote
    # to DEGRADED when the prior streak is older than CONNECTIVITY_WINDOW).
    if acc.connectivity_state != ConnectivityState.UNREACHABLE.value:
        acc.connectivity_state = ConnectivityState.UNREACHABLE.value
        session.execute(
            delete(OutboxEvent).where(
                OutboxEvent.id > max_existing_outbox_id,
                OutboxEvent.account_id == account_id,
                OutboxEvent.event_type == OutboxEventType.ACCOUNT_UPDATED.value,
                OutboxEvent.payload["connectivity_state"].astext == ConnectivityState.DEGRADED.value,
            )
        )
    session.flush()


def recheck_unreachable_with_probe(
    session_factory: Any,
    *,
    provider_factory: Any = None,
    now: datetime | None = None,
    lease_s: float = UNREACHABLE_PROBE_LEASE_S,
) -> int:
    """Half-open real-probe closed loop for stale UNREACHABLE accounts.

    Phase 1 (short read tx): select due UNREACHABLE accounts (>= 15m or missing stamps).
    Phase 1b (short write tx): atomically claim a JSONB lease per account so only
    one distributed worker executes the probe.
    Phase 2 (outside any DB tx): run lightweight real reachability probe.
    Phase 3 (short write tx): restore CONNECTED (+ enqueue discovery if needed),
    invalidate credential on AUTH error, or refresh UNREACHABLE backoff timestamp.
    """
    current_time = now or datetime.now(timezone.utc)
    factory = provider_factory or _default_unreachable_probe_provider

    with session_factory() as session:
        candidates = _select_overdue_unreachable_candidates(session, now=current_time)
        session.commit()

    probed = 0
    for candidate in candidates:
        account_id = candidate.account_snapshot.id
        try:
            with session_factory() as session:
                try:
                    claimed = _claim_unreachable_probe_lease(
                        session,
                        account_id=account_id,
                        now=current_time,
                        lease_s=lease_s,
                    )
                    if claimed:
                        session.commit()
                    else:
                        session.rollback()
                        continue
                except Exception:
                    session.rollback()
                    raise

            probe_exc: Exception | None = None
            try:
                _probe_account_reachability(candidate, provider_factory=factory)
            except Exception as exc:
                probe_exc = exc

            with session_factory() as session:
                try:
                    _settle_unreachable_probe_result(
                        session,
                        account_id=account_id,
                        probe_exc=probe_exc,
                        now=current_time,
                    )
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
            probed += 1
        except Exception:
            log.exception("unreachable half-open re-check failed for account %s", account_id)
    return probed


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

    # p088 / q3: half-open real-probe closed loop for stale open breakers.
    # Isolated from scheduling and patrol so a failure here cannot mask either.
    try:
        checked = recheck_unreachable_with_probe(Session)
        if checked:
            log.info("re-checked %s stale unreachable account breaker(s)", checked)
    except Exception:
        log.exception("connectivity breaker re-check sweep failed")
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


def _resolve_watchdog_timeout_s(*, poll_interval_s: float, max_idle_s: float) -> float | None:
    """Resolve main-loop stall watchdog timeout; <= 0 disables it."""
    raw_lag = os.environ.get("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG")
    healthcheck_max_lag = 60.0
    if raw_lag is not None and raw_lag.strip():
        try:
            parsed_lag = float(raw_lag)
            if math.isfinite(parsed_lag) and parsed_lag > 0:
                healthcheck_max_lag = parsed_lag
        except ValueError:
            pass
    default_timeout = max(
        180.0,
        healthcheck_max_lag * 3.0,
        max(poll_interval_s, max_idle_s) * 4.0,
    )
    raw = os.environ.get("MAIL_CORE_WORKER_WATCHDOG_TIMEOUT")
    if raw is None or not raw.strip():
        return default_timeout
    try:
        value = float(raw)
    except ValueError:
        log.warning(
            "invalid numeric environment setting MAIL_CORE_WORKER_WATCHDOG_TIMEOUT=%r; using default %s",
            raw,
            default_timeout,
        )
        return default_timeout
    if not math.isfinite(value):
        log.warning(
            "invalid numeric environment setting MAIL_CORE_WORKER_WATCHDOG_TIMEOUT=%r; using default %s",
            raw,
            default_timeout,
        )
        return default_timeout
    if value <= 0:
        return None
    return value


def _exit_on_watchdog_stall(_elapsed_s: float) -> None:
    """Terminate a stalled worker process so restart: unless-stopped recovers it."""
    for handler in logging.getLogger().handlers:
        try:
            handler.flush()
        except Exception:
            pass
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(1)


def _write_liveness_stamp_with_warning(
    *,
    progress: int,
    worker_id: str,
    now: float,
    last_warn_at: float | None,
    warn_interval_s: float = LIVENESS_WARN_INTERVAL_S,
) -> float | None:
    """Refresh liveness stamp and log a rate-limited warning on filesystem failures."""
    try:
        from mail_core.liveness import write_liveness_stamp

        write_liveness_stamp(progress=progress, worker_id=worker_id)
        return last_warn_at
    except Exception as exc:
        if last_warn_at is None or (now - last_warn_at) >= warn_interval_s:
            from mail_core.security.redact import safe_error

            log.warning("worker liveness stamp write failed: %s", safe_error(exc))
            return now
        return last_warn_at


def run(poll_interval_s: float | None = None, schedule_interval_s: float | None = None) -> None:
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
    schedule_interval = (
        schedule_interval_s
        if schedule_interval_s is not None
        else cfg.schedule_interval_s
    )
    log.info("worker %s starting (poll=%ss, max_idle=%ss)", worker_id, interval, max_idle)
    sleep_s = interval
    last_reclaim_at: float | None = None
    last_schedule_at: float | None = None
    last_liveness_warn_at: float | None = None
    schedule_thread: threading.Thread | None = None
    loop_progress = 0

    from mail_core.db.session import get_session_factory
    from mail_core.worker.heartbeat import WorkerHeartbeatLoop

    Session = get_session_factory()
    watchdog_timeout_s = _resolve_watchdog_timeout_s(
        poll_interval_s=interval,
        max_idle_s=max_idle,
    )
    heartbeat_loop = WorkerHeartbeatLoop(
        worker_id,
        Session,
        interval_s=heartbeat_interval,
        watchdog_timeout_s=watchdog_timeout_s,
        on_watchdog_stall=_exit_on_watchdog_stall if watchdog_timeout_s is not None else None,
    )
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
            # t095 AC-005: refresh the filesystem liveness stamp each loop so
            # a probe can verify the main loop is alive AND progressing without
            # a DB query or cold interpreter start.
            loop_progress += 1
            mark_progress = getattr(heartbeat_loop, "mark_progress", None)
            if callable(mark_progress):
                mark_progress()
            last_liveness_warn_at = _write_liveness_stamp_with_warning(
                progress=loop_progress,
                worker_id=worker_id,
                now=now,
                last_warn_at=last_liveness_warn_at,
            )
            if last_reclaim_at is None or now - last_reclaim_at >= reclaim_interval:
                last_reclaim_at = now
                try:
                    _reclaim_once()
                except Exception as exc:  # pragma: no cover
                    from mail_core.security.redact import safe_error

                    log.error("reclaim sweep failed: %s", safe_error(exc))

            if last_schedule_at is None or now - last_schedule_at >= schedule_interval:
                if schedule_thread is not None and schedule_thread.is_alive():
                    log.debug("previous periodic schedule sweep still in-flight; skipping new spawn")
                else:
                    last_schedule_at = now
                    try:
                        # AC-009: run periodic schedule / patrol sweeps asynchronously
                        # with single-flight protection so network probing never blocks task claiming.
                        schedule_thread = threading.Thread(
                            target=_schedule_periodic_sync_once,
                            name="worker-periodic-schedule",
                            daemon=True,
                        )
                        schedule_thread.start()
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
        if schedule_thread is not None and schedule_thread.is_alive():
            schedule_thread.join(timeout=2.0)
    log.info("worker loop stopped")


if __name__ == "__main__":
    run()
