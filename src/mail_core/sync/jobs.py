"""Worker job claim via SELECT … FOR UPDATE SKIP LOCKED (architecture §7.4–7.5)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import JobStatus
from mail_core.mail.storage.models import SyncRequestTargetJob, WorkerJob

DEFAULT_MAX_ATTEMPTS = 8
DEFAULT_RECLAIM_LIMIT = 100


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


def _record_claimed_followup(
    job: WorkerJob,
    *,
    payload: dict,
    priority: int,
    run_after: datetime,
) -> None:
    p = dict(job.payload or {})
    next_req = dict(p.get("_queue_next") or {})
    merged_payload = dict(next_req.get("payload") or {})
    for k, v in payload.items():
        if not k.startswith("_"):
            merged_payload[k] = v

    current_pri = next_req.get("priority", priority)
    merged_priority = min(current_pri, priority)

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
    }
    # A successor generation pre-allocated for sync-request bindings (R06)
    # must survive later claimed-job wakeups merging into _queue_next.
    if next_req.get("execution_generation"):
        queue_next_record["execution_generation"] = next_req["execution_generation"]
    p["_queue_next"] = queue_next_record
    p["_followup_needed"] = True
    p["_followup_run_after"] = merged_ra.isoformat()
    job.payload = p


def _merge_into_pending_job(
    job: WorkerJob,
    *,
    payload: dict,
    priority: int,
    run_after: datetime,
) -> None:
    p = dict(job.payload or {})
    for k, v in payload.items():
        if not k.startswith("_"):
            p[k] = v
    job.payload = p
    job.priority = min(job.priority, priority)
    if job.run_after is None or run_after < job.run_after:
        job.run_after = run_after


def enqueue_job(
    session: Session,
    *,
    job_type: str,
    account_id: uuid.UUID | None = None,
    payload: dict | None = None,
    priority: int = 100,
    run_after: datetime | None = None,
    dedupe_key: str | None = None,
) -> WorkerJob:
    """Enqueue a job. If ``dedupe_key`` matches a PENDING/CLAIMED row, atomically merge and wake."""
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
                    )
                    session.flush()
                    return existing
                elif existing.status == JobStatus.CLAIMED.value:
                    _record_claimed_followup(
                        existing,
                        payload=req_payload,
                        priority=priority,
                        run_after=target_run_after,
                    )
                    session.flush()
                    return existing

        job = WorkerJob(
            job_type=job_type,
            account_id=account_id,
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
) -> list[WorkerJob]:
    """Claim up to `limit` pending jobs. Must be called inside a short transaction."""
    now = now or datetime.now(timezone.utc)
    stmt = (
        select(WorkerJob)
        .where(WorkerJob.status == JobStatus.PENDING.value)
        .where(WorkerJob.run_after <= now)
        .order_by(WorkerJob.priority.asc(), WorkerJob.created_at.asc())
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    if job_types:
        stmt = stmt.where(WorkerJob.job_type.in_(list(job_types)))
    if account_id is not None:
        stmt = stmt.where(WorkerJob.account_id == account_id)
    rows = list(session.scalars(stmt).all())
    for job in rows:
        job.status = JobStatus.CLAIMED.value
        job.locked_by = worker_id
        job.locked_at = now
        job.attempts = int(job.attempts) + 1
    session.flush()
    if rows:
        # Sync-request bindings observing these executions become running.
        from mail_core.sync.execution import mark_bindings_running

        mark_bindings_running(session, rows)
    return rows


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

    followup_was_scheduled = bool(result and result.get("followup_scheduled")) and not bool(
        result and result.get("followup_coalesced")
    )
    handler_has_more = bool(result and result.get("has_more"))

    needs_successor = not followup_was_scheduled and (
        bool(queue_next) or bool(has_followup_flag) or handler_has_more
    )

    successor_job = None
    if needs_successor:
        successor_payload: dict = {}
        for k, v in payload.items():
            if not k.startswith("_"):
                successor_payload[k] = v

        successor_priority = locked_job.priority
        successor_run_after = datetime.now(timezone.utc)

        if queue_next and isinstance(queue_next, dict):
            req_pl = queue_next.get("payload") or {}
            for k, v in req_pl.items():
                if not k.startswith("_"):
                    successor_payload[k] = v
            if "priority" in queue_next:
                successor_priority = queue_next["priority"]
            if "run_after" in queue_next:
                try:
                    successor_run_after = datetime.fromisoformat(queue_next["run_after"])
                except (ValueError, TypeError):
                    pass
        elif payload.get("_followup_run_after"):
            try:
                successor_run_after = datetime.fromisoformat(payload["_followup_run_after"])
            except (ValueError, TypeError):
                pass

        if result and result.get("next_run_after"):
            successor_run_after = result["next_run_after"]

        # Requests that bound this CLAIMED job's successor carry the
        # generation pre-allocated in _queue_next (design §5.2); the
        # successor must be created with exactly that generation.
        successor_generation = None
        if queue_next and isinstance(queue_next, dict) and queue_next.get("execution_generation"):
            try:
                successor_generation = uuid.UUID(str(queue_next["execution_generation"]))
            except (ValueError, TypeError):
                successor_generation = None

        locked_job.status = JobStatus.DONE.value
        locked_job.locked_by = None
        locked_job.locked_at = None
        clean_p = {
            k: v
            for k, v in payload.items()
            if not k.startswith("_queue_") and not k.startswith("_followup_")
        }
        locked_job.payload = clean_p
        session.flush()

        successor_kwargs: dict = {}
        if successor_generation is not None:
            successor_kwargs["execution_generation"] = successor_generation
        successor_job = WorkerJob(
            job_type=locked_job.job_type,
            account_id=locked_job.account_id,
            payload=successor_payload,
            priority=successor_priority,
            run_after=successor_run_after,
            status=JobStatus.PENDING.value,
            dedupe_key=locked_job.dedupe_key,
            **successor_kwargs,
        )
        session.add(successor_job)
        session.flush()
        if successor_generation is not None:
            session.execute(
                update(SyncRequestTargetJob)
                .where(
                    SyncRequestTargetJob.execution_generation == successor_generation,
                    SyncRequestTargetJob.job_id.is_(None),
                )
                .values(job_id=successor_job.id)
            )
    else:
        locked_job.status = JobStatus.DONE.value
        locked_job.locked_by = None
        locked_job.locked_at = None
        clean_p = {
            k: v
            for k, v in payload.items()
            if not k.startswith("_queue_") and not k.startswith("_followup_")
        }
        locked_job.payload = clean_p
        session.flush()

    # Settle sync-request bindings in this same transaction, before the
    # current execution ends: open targets are carried onto the successor
    # (except periodic poll successors), finished ones are aggregated into
    # their requests (design §5.2). Lock order: this WorkerJob row is
    # already locked above; settlement then takes generation → target →
    # request locks.
    from mail_core.sync.execution import refresh_requests, settle_job_bindings

    request_ids = settle_job_bindings(
        session, locked_job, outcome="complete", result=result, successor=successor_job
    )
    refresh_requests(session, request_ids)

    return successor_job


def reschedule_job(
    session: Session,
    job: WorkerJob,
    *,
    worker_id: str | None = None,
    delay_seconds: float = 5.0,
    now: datetime | None = None,
) -> None:
    """Delay a job *without* counting a failure (design §7 deferral).

    Used for local capacity/control deferrals (provider connection
    budget saturated, slot control connection failed): the job returns
    to PENDING with a short delay, ``failure_attempts`` and
    ``last_error`` are untouched, and bound sync-request targets stay
    open on the same execution generation.
    """
    _assert_job_owner(job, worker_id)
    now = now or datetime.now(timezone.utc)
    delay = max(0.5, float(delay_seconds))
    job.status = JobStatus.PENDING.value
    job.run_after = now + timedelta(seconds=delay)
    job.locked_by = None
    job.locked_at = None
    session.flush()
    from mail_core.sync.execution import refresh_requests, settle_job_bindings

    refresh_requests(session, settle_job_bindings(session, job, outcome="retriable"))


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


def fail_job(
    session: Session,
    job: WorkerJob,
    error: BaseException | str,
    *,
    worker_id: str | None = None,
    max_attempts: int | None = None,
    now: datetime | None = None,
) -> None:
    """Count a failed execution and requeue with backoff until the failure cap."""
    _assert_job_owner(job, worker_id)
    now = now or datetime.now(timezone.utc)
    cap = max_attempts if max_attempts is not None else _max_attempts()
    from mail_core.security.redact import safe_error

    job.last_error = safe_error(error) or None
    if hasattr(job, "failure_attempts"):
        failure_attempts = int(job.failure_attempts) + 1
    else:  # Compatibility for minimal job test doubles without the mapped field.
        failure_attempts = int(job.attempts)
    job.failure_attempts = failure_attempts
    if failure_attempts < cap:
        delay = backoff_seconds(failure_attempts)
        if hasattr(error, "retry_after_seconds") and getattr(error, "retry_after_seconds", None) is not None:
            try:
                retry_after = float(getattr(error, "retry_after_seconds"))
                if retry_after > 0:
                    delay = max(delay, retry_after)
            except (ValueError, TypeError):
                pass
        job.status = JobStatus.PENDING.value
        job.run_after = now + timedelta(seconds=delay)
        job.locked_by = None
        job.locked_at = None
        session.flush()
        # Retriable failure: bound targets stay open on the same generation.
        from mail_core.sync.execution import refresh_requests, settle_job_bindings

        refresh_requests(session, settle_job_bindings(session, job, outcome="retriable"))
        return
    else:
        job.status = JobStatus.FAILED.value
        job.locked_by = None
        job.locked_at = None
    session.flush()
    # Terminal failure: bound targets fail with a stable code + sanitized text.
    from mail_core.sync.execution import refresh_requests, settle_job_bindings

    refresh_requests(
        session,
        settle_job_bindings(
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
) -> int:
    """Requeue claims whose ``locked_at`` heartbeat is older than ``older_than``."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - older_than
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
    request_ids: set[uuid.UUID] = set()
    for job in rows:
        job.status = JobStatus.PENDING.value
        job.locked_by = None
        job.locked_at = None
        suffix = "|reclaimed_stale_claim"
        prev = job.last_error or ""
        if suffix not in prev:
            job.last_error = (prev + suffix)[:2000]
    session.flush()
    if rows:
        # Reclaim keeps the job's execution_generation; its bindings go back
        # to queued rather than failing (design §5.1).
        from mail_core.sync.execution import refresh_requests, reset_bindings_for_job

        for job in rows:
            request_ids |= reset_bindings_for_job(session, job)
        refresh_requests(session, request_ids)
    return len(rows)


def prune_completed_jobs(
    session: Session,
    *,
    older_than: timedelta = timedelta(days=7),
    now: datetime | None = None,
    limit: int = 1000,
) -> int:
    """Delete DONE and terminal FAILED jobs updated before cutoff to bound table growth."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - older_than
    ids = list(
        session.scalars(
            select(WorkerJob.id)
            .where(WorkerJob.status.in_([JobStatus.DONE.value, JobStatus.FAILED.value]))
            .where(WorkerJob.updated_at < cutoff)
            .order_by(WorkerJob.updated_at.asc())
            .limit(max(1, int(limit)))
        ).all()
    )
    if not ids:
        return 0
    session.execute(delete(WorkerJob).where(WorkerJob.id.in_(ids)))
    session.flush()
    return len(ids)
