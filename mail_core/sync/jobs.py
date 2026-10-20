"""Worker job claim via SELECT … FOR UPDATE SKIP LOCKED (architecture §7.4–7.5)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import JobStatus
from mail_core.mail.storage.models import WorkerJob


def enqueue_job(
    session: Session,
    *,
    job_type: str,
    account_id: uuid.UUID | None = None,
    payload: dict | None = None,
    priority: int = 100,
    run_after: datetime | None = None,
) -> WorkerJob:
    job = WorkerJob(
        job_type=job_type,
        account_id=account_id,
        payload=payload or {},
        priority=priority,
        run_after=run_after or datetime.now(timezone.utc),
        status=JobStatus.PENDING.value,
    )
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


def complete_job(session: Session, job: WorkerJob) -> None:
    job.status = JobStatus.DONE.value
    session.flush()


def fail_job(session: Session, job: WorkerJob, error: str) -> None:
    job.status = JobStatus.FAILED.value
    job.last_error = error
    session.flush()
