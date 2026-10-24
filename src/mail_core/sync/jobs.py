"""Worker job claim via SELECT … FOR UPDATE SKIP LOCKED (architecture §7.4–7.5)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import JobStatus
from mail_core.mail.storage.models import WorkerJob

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
    """Enqueue a job. If ``dedupe_key`` matches a PENDING/CLAIMED row, return it."""
    if dedupe_key:
        existing = session.scalar(
            select(WorkerJob)
            .where(WorkerJob.dedupe_key == dedupe_key)
            .where(WorkerJob.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value]))
            .limit(1)
        )
        if existing is not None:
            if existing.status == JobStatus.CLAIMED.value:
                p = dict(existing.payload or {})
                p["_followup_needed"] = True
                if run_after:
                    p["_followup_run_after"] = run_after.isoformat()
                existing.payload = p
                session.flush()
            return existing
    job = WorkerJob(
        job_type=job_type,
        account_id=account_id,
        payload=payload or {},
        priority=priority,
        run_after=run_after or datetime.now(timezone.utc),
        status=JobStatus.PENDING.value,
        dedupe_key=dedupe_key,
    )
    if dedupe_key:
        try:
            with session.begin_nested():
                session.add(job)
                session.flush()
        except IntegrityError:
            existing = session.scalar(
                select(WorkerJob)
                .where(WorkerJob.dedupe_key == dedupe_key)
                .where(WorkerJob.status.in_([JobStatus.PENDING.value, JobStatus.CLAIMED.value]))
                .limit(1)
            )
            if existing is not None:
                if existing.status == JobStatus.CLAIMED.value:
                    p = dict(existing.payload or {})
                    p["_followup_needed"] = True
                    if run_after:
                        p["_followup_run_after"] = run_after.isoformat()
                    existing.payload = p
                    session.flush()
                return existing
            latest = session.scalar(
                select(WorkerJob)
                .where(WorkerJob.dedupe_key == dedupe_key)
                .order_by(WorkerJob.created_at.desc())
                .limit(1)
            )
            if latest is not None:
                return latest
            raise
    else:
        session.add(job)
        session.flush()
    return job


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
    return rows


def complete_job(session: Session, job: WorkerJob, *, worker_id: str | None = None) -> None:
    _assert_job_owner(job, worker_id)
    job.status = JobStatus.DONE.value
    job.locked_by = None
    job.locked_at = None
    session.flush()


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
    else:
        job.status = JobStatus.FAILED.value
    session.flush()


def reclaim_stale_claims(
    session: Session,
    *,
    older_than: timedelta = timedelta(minutes=5),
    now: datetime | None = None,
    limit: int = DEFAULT_RECLAIM_LIMIT,
) -> int:
    """Return CLAIMED jobs whose lock is older than ``older_than`` to PENDING."""
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
    for job in rows:
        job.status = JobStatus.PENDING.value
        job.locked_by = None
        job.locked_at = None
        suffix = "|reclaimed_stale_claim"
        prev = job.last_error or ""
        if suffix not in prev:
            job.last_error = (prev + suffix)[:2000]
    session.flush()
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
