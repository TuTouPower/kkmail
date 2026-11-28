"""Worker job claim via SELECT … FOR UPDATE SKIP LOCKED (architecture §7.4–7.5)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from sqlalchemy import delete, exists, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import (
    ExecutionOrigin,
    JobStatus,
    JobType,
    normalize_execution_origin,
)
from mail_core.mail.domain.failures import StructuredFailure
from mail_core.mail.storage.models import (
    SyncRequest,
    SyncRequestTarget,
    SyncRequestTargetJob,
    WorkerJob,
)
from mail_core.sync.context import coalesce_execution_origin
from mail_core.sync.retention import (
    COMPLETED_JOB_RETENTION,
    COMPLETED_JOB_PRUNE_BATCH,
    refresh_table_stats_if_bulk,
)


def _advance_delta_watermark_on_settle(
    session: Session,
    job: WorkerJob,
    *,
    settled: bool,
    result: dict | None = None,
    now: datetime | None = None,
) -> None:
    """t094: advance the authoritative delta watermark in the settling transaction.

    Called from ``complete_job`` (with the job result) and ``fail_job`` (terminal
    failure) so the watermark and terminal job state commit atomically. Only a
    genuine delta execution-chain settlement advances it; deferrals, handoffs
    and superseded runs are filtered by ``is_delta_settled_result``. Monotonic
    advancement stops a superseded execution that commits late from moving the
    watermark backwards.
    """
    if getattr(job, "job_type", None) != JobType.SYNC_FOLDER_DELTA.value:
        return
    if getattr(job, "account_id", None) is None:
        return
    payload = getattr(job, "payload", None) or {}
    folder_raw = payload.get("folder_id")
    if not folder_raw:
        return
    if settled:
        if result is not None:
            from mail_core.sync.checkpoints import is_delta_settled_result

            if not is_delta_settled_result(result):
                return
    else:
        return
    try:
        folder_id = uuid.UUID(str(folder_raw))
    except (ValueError, AttributeError, TypeError):
        return
    from mail_core.sync.checkpoints import advance_delta_settlement_watermark

    # t094: capture the execution's fencing token from the delta result when
    # present; the monotonic token comparison in the watermark helper rejects
    # a superseded execution that commits late.
    fencing_token = None
    if result is not None and result.get("fencing_token") is not None:
        try:
            fencing_token = int(result["fencing_token"])
        except (ValueError, TypeError):
            fencing_token = None
    advance_delta_settlement_watermark(
        session,
        account_id=job.account_id,
        folder_id=folder_id,
        settled_at=now,
        fencing_token=fencing_token,
    )

DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_RECLAIM_LIMIT = 100

LEASE_JOB_TYPES: frozenset[str] = frozenset({
    JobType.SYNC_ACCOUNT_FOLDERS.value,
    JobType.SYNC_FOLDER_METADATA.value,
    JobType.SYNC_FOLDER_DELTA.value,
    JobType.RECONCILE_FOLDER.value,
    JobType.REMOTE_OPERATION_PUSH.value,
})


class JobOwnershipError(RuntimeError):
    """complete_job/fail_job called without owning the CLAIMED row."""


def _assert_job_owner(job: WorkerJob, worker_id: str | None) -> None:
    if worker_id is None:
        return
    if job.status != JobStatus.CLAIMED.value:
        raise JobOwnershipError(
            f"job {job.id} status={job.status!r} expected CLAIMED"
        )
    if job.locked_by != worker_id:
        raise JobOwnershipError(
            f"job {job.id} locked_by={job.locked_by!r} != worker_id={worker_id!r}"
        )


def _max_attempts() -> int:
    return int(os.environ.get("MAIL_CORE_JOB_MAX_ATTEMPTS") or str(DEFAULT_MAX_ATTEMPTS))


def backoff_seconds(attempts: int) -> int:
    """Exponential backoff after a failed attempt (attempts is post-increment)."""
    # attempts=1 → 1s, 2 → 2s, 3 → 4s … capped at 1h
    exp = max(0, int(attempts) - 1)
    return min(3600, 2**exp)


_LINEAGE_PAYLOAD_KEYS = frozenset({"request_id", "parent_request_id", "full", "scan_generation"})


def _merge_coalesced_payload(
    base_payload: dict[str, Any],
    incoming_payload: dict[str, Any],
    *,
    existing_origin: ExecutionOrigin,
    incoming_origin: ExecutionOrigin,
    merged_origin: ExecutionOrigin,
) -> dict[str, Any]:
    """Merge non-internal keys on dedupe coalescing without leaking cross-origin request lineage."""
    merged = {k: v for k, v in base_payload.items() if k != "background"}
    if existing_origin is ExecutionOrigin.BACKGROUND and incoming_origin is ExecutionOrigin.FOREGROUND:
        for key in _LINEAGE_PAYLOAD_KEYS:
            merged.pop(key, None)
    for k, v in incoming_payload.items():
        if k.startswith("_") or k == "background":
            continue
        if (
            merged_origin is ExecutionOrigin.FOREGROUND
            and incoming_origin is ExecutionOrigin.BACKGROUND
            and k in _LINEAGE_PAYLOAD_KEYS
        ):
            continue
        merged[k] = v
    return merged


def _record_claimed_followup(
    job: WorkerJob,
    *,
    payload: dict,
    priority: int,
    run_after: datetime,
    execution_origin: ExecutionOrigin | str,
) -> None:
    p = dict(job.payload or {})
    next_req = dict(p.get("_queue_next") or {})
    base_next_payload = dict(next_req.get("payload") or {})

    current_pri = next_req.get("priority", priority)
    merged_priority = min(current_pri, priority)
    incoming_origin = normalize_execution_origin(execution_origin)
    existing_next_raw = next_req.get("execution_origin")
    existing_origin = (
        normalize_execution_origin(existing_next_raw)
        if existing_next_raw is not None
        else incoming_origin
    )
    merged_origin = (
        coalesce_execution_origin(existing_origin, incoming_origin)
        if existing_next_raw is not None
        else incoming_origin
    )
    merged_payload = _merge_coalesced_payload(
        base_next_payload,
        payload,
        existing_origin=existing_origin,
        incoming_origin=incoming_origin,
        merged_origin=merged_origin,
    )

    current_run_after_str = next_req.get("run_after")
    if current_run_after_str:
        try:
            current_ra = datetime.fromisoformat(current_run_after_str)
            merged_ra = min(current_ra, run_after)
        except (ValueError, TypeError):
            merged_ra = run_after
    else:
        merged_ra = run_after

    queue_next_record: dict = {
        "payload": merged_payload,
        "priority": merged_priority,
        "run_after": merged_ra.isoformat(),
        "execution_origin": merged_origin.value,
    }
    p["_queue_next"] = queue_next_record
    p["_followup_needed"] = True
    p["_followup_run_after"] = merged_ra.isoformat()
    job.payload = p


def _backoff_floor(job: WorkerJob, payload: dict) -> datetime | None:
    """Earliest time a backoff job may run again, if it is in backoff (A347).

    ``fail_job`` stamps ``_backoff_until`` into the payload when it
    requeues with backoff. Rows requeued before the stamp existed are
    recognised by ``failure_attempts > 0`` with a future ``run_after``.
    """
    raw = payload.get("_backoff_until")
    if raw:
        try:
            return datetime.fromisoformat(str(raw))
        except (ValueError, TypeError):
            pass
    if int(getattr(job, "failure_attempts", 0) or 0) > 0:
        return job.run_after
    return None


def _merge_into_pending_job(
    job: WorkerJob,
    *,
    payload: dict,
    priority: int,
    run_after: datetime,
    execution_origin: ExecutionOrigin | str,
) -> None:
    existing_origin = normalize_execution_origin(job.execution_origin)
    incoming_origin = normalize_execution_origin(execution_origin)
    merged_origin = coalesce_execution_origin(existing_origin, incoming_origin)
    job.payload = _merge_coalesced_payload(
        dict(job.payload or {}),
        payload,
        existing_origin=existing_origin,
        incoming_origin=incoming_origin,
        merged_origin=merged_origin,
    )
    job.priority = min(job.priority, priority)
    job.execution_origin = merged_origin.value
    floor = _backoff_floor(job, job.payload)
    if floor is not None and run_after < floor:
        # A dedupe merge must not wake a job out of its backoff window:
        # payload/priority merge above still applies, timing does not.
        if job.run_after is None or job.run_after < floor:
            job.run_after = floor
        return
    if job.run_after is None or run_after < job.run_after:
        job.run_after = run_after


def enqueue_job(
    session: Session,
    *,
    job_type: str,
    execution_origin: ExecutionOrigin | str,
    account_id: uuid.UUID | None = None,
    payload: dict | None = None,
    priority: int = 100,
    run_after: datetime | None = None,
    dedupe_key: str | None = None,
) -> WorkerJob:
    """Enqueue a job with mandatory typed ``execution_origin``."""
    origin_value = normalize_execution_origin(execution_origin).value
    now_utc = datetime.now(timezone.utc)
    target_run_after = run_after or now_utc
    req_payload = payload or {}

    attempts = 0
    while attempts < 10:
        attempts += 1
        if dedupe_key:
            stmt = (
                select(WorkerJob)
                .where(WorkerJob.dedupe_key == dedupe_key)
                .where(WorkerJob.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value]))
                .with_for_update()
                .limit(1)
            )
            existing = session.scalar(stmt)
            if existing is not None:
                session.refresh(existing)
                if existing.status == JobStatus.PENDING.value:
                    _merge_into_pending_job(
                        existing,
                        payload=req_payload,
                        priority=priority,
                        run_after=target_run_after,
                        execution_origin=origin_value,
                    )
                    session.flush()
                    return existing
                elif existing.status == JobStatus.CLAIMED.value:
                    _record_claimed_followup(
                        existing,
                        payload=req_payload,
                        priority=priority,
                        run_after=target_run_after,
                        execution_origin=origin_value,
                    )
                    session.flush()
                    return existing

        job = WorkerJob(
            job_type=job_type,
            account_id=account_id,
            execution_origin=origin_value,
            payload=dict(req_payload),
            priority=priority,
            run_after=target_run_after,
            status=JobStatus.PENDING.value,
            dedupe_key=dedupe_key,
        )
        if dedupe_key:
            try:
                with session.begin_nested():
                    session.add(job)
                    session.flush()
                return job
            except IntegrityError as exc:
                err_text = str(exc).lower()
                if "dedupe_key" in err_text or "unique" in err_text:
                    continue
                raise
        else:
            session.add(job)
            session.flush()
            return job

    raise RuntimeError(f"failed to enqueue job with dedupe_key {dedupe_key!r} after retries")


def claim_jobs(
    session: Session,
    *,
    worker_id: str,
    limit: int = 1,
    job_types: Sequence[str] | None = None,
    account_id: uuid.UUID | None = None,
    now: datetime | None = None,
    exclude_background: bool = False,
    exclude_busy_lease_accounts: bool = True,
) -> list[WorkerJob]:
    """Claim up to `limit` pending jobs. Must be called inside a short transaction."""
    from sqlalchemy import func, or_

    now = now or datetime.now(timezone.utc)
    stmt = (
        select(WorkerJob)
        .where(WorkerJob.status == JobStatus.PENDING.value)
        .where(WorkerJob.run_after <= now)
    )
    if job_types:
        stmt = stmt.where(WorkerJob.job_type.in_(list(job_types)))
    if account_id is not None:
        stmt = stmt.where(WorkerJob.account_id == account_id)

    if exclude_background:
        bind = session.get_bind()
        if bind is not None and bind.dialect.name == "postgresql":
            has_mid = WorkerJob.payload.has_key("message_id")
        else:
            has_mid = func.json_extract(WorkerJob.payload, "$.message_id").is_not(None)
        stmt = stmt.where(
            or_(
                WorkerJob.job_type != JobType.ARCHIVE_MIME_BATCH.value,
                has_mid,
            )
        )

    if exclude_busy_lease_accounts:
        active_lease_accounts = (
            select(WorkerJob.account_id)
            .where(WorkerJob.status == JobStatus.CLAIMED.value)
            .where(WorkerJob.job_type.in_(list(LEASE_JOB_TYPES)))
            .where(WorkerJob.account_id.is_not(None))
        )
        stmt = stmt.where(
            or_(
                WorkerJob.job_type.not_in(list(LEASE_JOB_TYPES)),
                WorkerJob.account_id.is_(None),
                WorkerJob.account_id.not_in(active_lease_accounts),
            )
        )

    stmt = (
        stmt.order_by(WorkerJob.priority.asc(), WorkerJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    rows = list(session.scalars(stmt).all())
    claimed_rows: list[WorkerJob] = []
    seen_lease_accounts: set[uuid.UUID] = set()

    for job in rows:
        if exclude_busy_lease_accounts and job.job_type in LEASE_JOB_TYPES and job.account_id is not None:
            if job.account_id in seen_lease_accounts:
                continue
            seen_lease_accounts.add(job.account_id)
        job.status = JobStatus.CLAIMED.value
        job.locked_by = worker_id
        job.locked_at = now
        job.attempts = int(job.attempts) + 1
        claimed_rows.append(job)

    session.flush()
    if claimed_rows:
        # Sync-request links observing these executions become running.
        from mail_core.sync.execution import mark_links_running

        mark_links_running(session, claimed_rows)
    return claimed_rows


def _resolve_successor_origin(locked_job: WorkerJob, queue_next: Any) -> str:
    """Resolve execution_origin for a successor job from _queue_next or parent job."""
    if isinstance(queue_next, dict) and queue_next.get("execution_origin") is not None:
        return normalize_execution_origin(queue_next["execution_origin"]).value
    return normalize_execution_origin(locked_job.execution_origin).value


def _build_successor_payload(
    base_payload: dict[str, Any],
    queue_next: Any,
    *,
    existing_origin: ExecutionOrigin,
    successor_origin: ExecutionOrigin,
) -> dict[str, Any]:
    """Build successor payload while stripping settled cross-origin request lineage keys."""
    clean_base = {
        k: v
        for k, v in base_payload.items()
        if not k.startswith("_")
        and k != "background"
        and (existing_origin is successor_origin or k not in _LINEAGE_PAYLOAD_KEYS)
    }
    incoming = queue_next.get("payload") or {} if isinstance(queue_next, dict) else {}
    return _merge_coalesced_payload(
        clean_base,
        incoming,
        existing_origin=existing_origin,
        incoming_origin=successor_origin,
        merged_origin=successor_origin,
    )


def _resolve_successor_schedule(
    locked_job: WorkerJob,
    queue_next: Any,
    payload: dict[str, Any],
    result: dict[str, Any] | None,
) -> tuple[int, datetime]:
    """Determine priority and run_after for a successor WorkerJob."""
    priority = locked_job.priority
    run_after = datetime.now(timezone.utc)
    if queue_next and isinstance(queue_next, dict):
        if "priority" in queue_next:
            priority = queue_next["priority"]
        if "run_after" in queue_next:
            try:
                run_after = datetime.fromisoformat(queue_next["run_after"])
            except (ValueError, TypeError):
                pass
    elif payload.get("_followup_run_after"):
        try:
            run_after = datetime.fromisoformat(payload["_followup_run_after"])
        except (ValueError, TypeError):
            pass
    if result and result.get("next_run_after"):
        run_after = result["next_run_after"]
    return priority, run_after


def complete_job(
    session: Session,
    job: WorkerJob,
    *,
    worker_id: str | None = None,
    result: dict | None = None,
) -> WorkerJob | None:
    _assert_job_owner(job, worker_id)

    locked_job = session.scalar(
        select(WorkerJob).where(WorkerJob.id == job.id).with_for_update()
    )
    if locked_job is None:
        return None
    session.refresh(locked_job)
    _assert_job_owner(locked_job, worker_id)

    payload = dict(locked_job.payload or {})
    queue_next = payload.get("_queue_next")
    has_followup_flag = payload.get("_followup_needed")

    from mail_core.sync.execution import has_waiting_links

    handler_has_more = bool(result and result.get("has_more"))
    # A target that arrived while this job was CLAIMED still needs a fresh
    # pass. The successor is materialized first and its links are migrated
    # onto it, so no request ever observes a merely planned execution.
    needs_successor = bool(queue_next) or bool(has_followup_flag) or handler_has_more or has_waiting_links(session, locked_job)

    successor_job = None
    locked_origin = normalize_execution_origin(locked_job.execution_origin)
    successor_origin = _resolve_successor_origin(locked_job, queue_next)
    if needs_successor:
        successor_payload = _build_successor_payload(
            payload,
            queue_next,
            existing_origin=locked_origin,
            successor_origin=ExecutionOrigin(successor_origin),
        )
        successor_priority, successor_run_after = _resolve_successor_schedule(
            locked_job, queue_next, payload, result
        )

    locked_job.status = JobStatus.DONE.value
    locked_job.locked_by = None
    locked_job.locked_at = None
    locked_job.payload = {
        k: v
        for k, v in payload.items()
        if not k.startswith("_queue_") and not k.startswith("_followup_")
    }
    session.flush()

    if needs_successor:
        successor_job = WorkerJob(
            job_type=locked_job.job_type,
            account_id=locked_job.account_id,
            execution_origin=successor_origin,
            payload=successor_payload,
            priority=successor_priority,
            run_after=successor_run_after,
            status=JobStatus.PENDING.value,
            dedupe_key=locked_job.dedupe_key,
        )
        session.add(successor_job)
        session.flush()
        from mail_core.sync.execution import migrate_waiting_links

        migrate_waiting_links(session, from_job=locked_job, to_job=successor_job)

    # Settle links observing this job in the same transaction. Waiting links
    # have already moved to the successor; finished ones are aggregated.
    from mail_core.sync.execution import refresh_requests, settle_job_links

    request_ids = settle_job_links(session, locked_job, outcome="complete", result=result)
    refresh_requests(session, request_ids)
    _advance_delta_watermark_on_settle(session, locked_job, settled=True, result=result)

    return successor_job


def reschedule_job(
    session: Session,
    job: WorkerJob,
    *,
    worker_id: str | None = None,
    delay_seconds: float = 5.0,
    now: datetime | None = None,
    count_failure: bool = False,
    error: StructuredFailure | BaseException | str | None = None,
) -> None:
    """Requeue a job on the same row (framework-owned retry).

    * ``count_failure=False`` (default): a control deferral (capacity) that
      must not count as a failure — ``failure_attempts``/``last_error`` stay
      untouched and the delay is the caller-supplied one.
    * ``count_failure=True``: a retriable execution failure — the same job id
      is kept, ``failure_attempts`` is incremented, ``last_error`` is set, an
      exponential-backoff window is stamped, and the terminal failure cap is
      honoured via ``fail_job``.

    Both paths keep bound sync-request targets open on the same execution
    generation (``outcome="retriable"``); no successor job is created.
    """

    _assert_job_owner(job, worker_id)
    now = now or datetime.now(timezone.utc)

    if count_failure:
        # Delegate to the framework's single retry implementation: it owns
        # failure counting, exponential backoff, the retry_after hint, the
        # terminal cap and binding settlement.  No duplicate logic here.
        fail_job(session, job, error or "retriable failure", worker_id=worker_id, now=now)
        return

    delay = max(0.5, float(delay_seconds))
    job.status = JobStatus.PENDING.value
    job.run_after = now + timedelta(seconds=delay)
    job.locked_by = None
    job.locked_at = None
    session.flush()
    from mail_core.sync.execution import refresh_requests, settle_job_links

    refresh_requests(session, settle_job_links(session, job, outcome="retriable"))


def heartbeat_job_claim(
    session: Session,
    *,
    job_id: uuid.UUID,
    worker_id: str,
    locked_at: datetime,
    now: datetime | None = None,
) -> datetime | None:
    """Refresh locked_at only while the original claim still belongs to this worker."""
    heartbeat_at = now or datetime.now(timezone.utc)
    result = session.execute(
        update(WorkerJob)
        .where(WorkerJob.id == job_id)
        .where(WorkerJob.status == JobStatus.CLAIMED.value)
        .where(WorkerJob.locked_by == worker_id)
        .where(WorkerJob.locked_at == locked_at)
        .values(locked_at=heartbeat_at)
    )
    return heartbeat_at if result.rowcount == 1 else None


def _retry_after_delay(error: Any, default_delay: float) -> float:
    if isinstance(error, StructuredFailure):
        raw_retry: Any = error.retry_after_s
    elif isinstance(error, BaseException):
        raw_retry = StructuredFailure.from_exception(error).retry_after_s
    else:
        raw_retry = getattr(error, "retry_after_seconds", None)
    if raw_retry is None:
        return default_delay
    try:
        retry_after = float(raw_retry)
        return max(default_delay, retry_after) if retry_after > 0 else default_delay
    except (ValueError, TypeError):
        return default_delay


def _project_job_error(error: StructuredFailure | BaseException | str | None) -> str | None:
    from mail_core.security.redact import safe_error

    if isinstance(error, StructuredFailure):
        return error.format() or None
    if isinstance(error, BaseException):
        return StructuredFailure.from_exception(error).format() or None
    return safe_error(error) or None


def fail_job(
    session: Session,
    job: WorkerJob,
    error: StructuredFailure | BaseException | str | None,
    *,
    worker_id: str | None = None,
    max_attempts: int | None = None,
    now: datetime | None = None,
) -> None:
    """Count a failed execution and requeue with backoff until the failure cap."""
    _assert_job_owner(job, worker_id)
    now = now or datetime.now(timezone.utc)
    cap = max_attempts if max_attempts is not None else _max_attempts()

    job.last_error = _project_job_error(error)
    if hasattr(job, "failure_attempts"):
        failure_attempts = int(job.failure_attempts) + 1
    else:  # Compatibility for minimal job test doubles without the mapped field.
        failure_attempts = int(job.attempts)
    job.failure_attempts = failure_attempts
    if failure_attempts < cap:
        delay = _retry_after_delay(error, backoff_seconds(failure_attempts))
        job.status = JobStatus.PENDING.value
        job.run_after = now + timedelta(seconds=delay)
        job.locked_by = None
        job.locked_at = None
        # Stamp the backoff window so a dedupe merge in enqueue_job
        # cannot pull run_after earlier and defeat the backoff (A347).
        if isinstance(getattr(job, "payload", None), dict):
            stamped = dict(job.payload or {})
            stamped["_backoff_until"] = job.run_after.isoformat()
            job.payload = stamped
        session.flush()
        # Retriable failure: bound targets stay open on the same generation.
        from mail_core.sync.execution import refresh_requests, settle_job_links

        refresh_requests(session, settle_job_links(session, job, outcome="retriable"))
        return
    else:
        job.status = JobStatus.FAILED.value
        job.locked_by = None
        job.locked_at = None
        # t094: terminal failure is a delta execution-chain settlement (retry
        # exhausted); advance the watermark in this same commit so a failed
        # folder is still due on the next interval rather than stuck or spun.
        _advance_delta_watermark_on_settle(session, job, settled=True, result=None, now=now)
    session.flush()
    # Terminal failure: bound targets fail with a stable code + sanitized text.
    from mail_core.sync.execution import refresh_requests, settle_job_links

    refresh_requests(
        session,
        settle_job_links(
            session,
            job,
            outcome="failed",
            error_code="job_failed",
            safe_error=job.last_error,
        ),
    )


def reclaim_stale_claims(
    session: Session,
    *,
    older_than: timedelta = timedelta(minutes=5),
    now: datetime | None = None,
    limit: int = DEFAULT_RECLAIM_LIMIT,
    max_attempts: int | None = None,
) -> int:
    """Requeue claims whose ``locked_at`` heartbeat is older than ``older_than``.

    Every reclaim counts as a failure (``failure_attempts``): a job whose
    worker keeps dying mid-claim is a crash loop, not a fresh job each
    time. Once the count reaches the cap the job follows ``fail_job``'s
    terminal path (FAILED + bindings settled as failed) instead of being
    reclaimed forever (A148).
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - older_than
    cap = max_attempts if max_attempts is not None else _max_attempts()
    stmt = (
        select(WorkerJob)
        .where(WorkerJob.status == JobStatus.CLAIMED.value)
        .where(WorkerJob.locked_at.is_not(None))
        .where(WorkerJob.locked_at < cutoff)
        .order_by(WorkerJob.locked_at.asc())
        .with_for_update(skip_locked=True)
        .limit(max(1, int(limit)))
    )
    rows = list(session.scalars(stmt).all())
    requeued: list[WorkerJob] = []
    terminal: list[WorkerJob] = []
    for job in rows:
        if hasattr(job, "failure_attempts"):
            failure_attempts = int(job.failure_attempts or 0) + 1
        else:  # Compatibility for minimal job test doubles (see fail_job).
            failure_attempts = int(job.attempts) + 1
        job.failure_attempts = failure_attempts
        job.locked_by = None
        job.locked_at = None
        suffix = "|reclaimed_stale_claim"
        prev = job.last_error or ""
        if suffix not in prev:
            job.last_error = (prev + suffix)[:2000]
        if failure_attempts < cap:
            job.status = JobStatus.PENDING.value
            requeued.append(job)
        else:
            job.status = JobStatus.FAILED.value
            terminal.append(job)
    session.flush()
    if rows:
        from mail_core.sync.execution import refresh_requests, reset_links_for_job, settle_job_links

        request_ids: set[uuid.UUID] = set()
        # Reclaim keeps the same job row; its links go back to queued.
        for job in requeued:
            request_ids |= reset_links_for_job(session, job)
        # Terminal reclaims settle exactly like fail_job's cap path.
        for job in terminal:
            request_ids |= settle_job_links(
                session,
                job,
                outcome="failed",
                error_code="job_failed",
                safe_error=job.last_error,
            )
            # t094: a crash-loop job hitting the attempt cap is a terminal
            # delta settlement too; advance the watermark in this same commit.
            _advance_delta_watermark_on_settle(
                session, job, settled=True, result=None, now=now
            )
        refresh_requests(session, request_ids)
    return len(rows)


def prune_completed_jobs(
    session: Session,
    *,
    older_than: timedelta = COMPLETED_JOB_RETENTION,
    now: datetime | None = None,
    limit: int = COMPLETED_JOB_PRUNE_BATCH,
) -> int:
    """Delete terminal jobs past the retention window (t094 AC-003/007).

    A terminal job whose sync-request target OR parent sync-request is still
    open is excluded via correlated ``NOT EXISTS``: a failed target in a
    multi-target request still needs its links/state protected while sibling
    targets remain open. Only jobs whose links belong exclusively to already-
    settled targets and settled parent requests are reclaimable.
    """
    from mail_core.sync.execution import OPEN_LINK_STATES

    now = now or datetime.now(timezone.utc)
    cutoff = now - older_than
    open_request_link = exists(
        select(1)
        .select_from(SyncRequestTargetJob)
        .join(
            SyncRequestTarget,
            SyncRequestTarget.id == SyncRequestTargetJob.target_id,
        )
        .join(
            SyncRequest,
            SyncRequest.id == SyncRequestTarget.request_id,
        )
        .where(SyncRequestTargetJob.job_id == WorkerJob.id)
        .where(
            or_(
                SyncRequestTarget.state.in_(OPEN_LINK_STATES),
                SyncRequest.state.in_(OPEN_LINK_STATES),
            )
        )
    )
    ids = list(
        session.scalars(
            select(WorkerJob.id)
            .where(WorkerJob.status.in_([JobStatus.DONE.value, JobStatus.FAILED.value]))
            .where(WorkerJob.updated_at < cutoff)
            .where(~open_request_link)
            .order_by(WorkerJob.updated_at.asc())
            .limit(max(1, int(limit)))
        ).all()
    )
    if not ids:
        return 0
    session.execute(delete(WorkerJob).where(WorkerJob.id.in_(ids)))
    session.flush()
    if refresh_table_stats_if_bulk(len(ids), "worker_jobs"):
        session.execute(text("ANALYZE worker_jobs"))
    return len(ids)
