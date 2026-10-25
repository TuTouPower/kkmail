"""Job dispatch table for the worker process."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.accounts.credentials import get_credential_store
from mail_core.accounts.service import update_account_sync_status
from mail_core.mail.domain.enums import JobStatus, JobType, SyncStatus
from mail_core.mail.storage.models import Account, WorkerJob
from mail_core.sync.jobs import complete_job, fail_job

log = logging.getLogger("mail_core.worker.handlers")
_ACCOUNT_SYNC_JOB_TYPES = (
    JobType.SYNC_ACCOUNT_FOLDERS.value,
    JobType.SYNC_FOLDER_METADATA.value,
    JobType.SYNC_FOLDER_DELTA.value,
    JobType.RECONCILE_FOLDER.value,
)


def _recover_account_sync_status(session: Session, job: WorkerJob) -> None:
    if job.account_id is None or job.job_type not in _ACCOUNT_SYNC_JOB_TYPES:
        return
    account = session.get(Account, job.account_id)
    if account is None or not account.sync_enabled or account.sync_status != SyncStatus.FAILED.value:
        return
    active_error = session.scalar(
        select(WorkerJob.id)
        .where(
            WorkerJob.account_id == job.account_id,
            WorkerJob.job_type.in_(_ACCOUNT_SYNC_JOB_TYPES),
            WorkerJob.status.in_((JobStatus.PENDING.value, JobStatus.CLAIMED.value)),
            WorkerJob.last_error.is_not(None),
        )
        .limit(1)
    )
    if active_error is None:
        update_account_sync_status(session, job.account_id, SyncStatus.IDLE)


def _evaluate_result(session: Session, job: WorkerJob, result: dict, worker_id: str) -> bool:
    status = result.get("status")
    if (
        status in ("provider_error", "rate_limited")
        and job.account_id is not None
        and job.job_type in _ACCOUNT_SYNC_JOB_TYPES
    ):
        update_account_sync_status(
            session,
            job.account_id,
            SyncStatus.FAILED,
            error=str(result.get("error") or status),
        )
    if status in ("ok", "sync_disabled", "skipped", "rate_limited") or result.get("followup_scheduled"):
        payload = dict(job.payload or {})
        followup_was_scheduled = bool(result.get("followup_scheduled")) and not bool(
            result.get("followup_coalesced")
        )
        followup = not followup_was_scheduled and bool(result.get("has_more") or payload.get("_followup_needed"))
        next_run_after = None if followup_was_scheduled else result.get("next_run_after")
        if not followup_was_scheduled and not next_run_after and payload.get("_followup_run_after"):
            try:
                next_run_after = datetime.fromisoformat(payload["_followup_run_after"])
            except (TypeError, ValueError):
                log.warning(
                    "job %s has unparseable _followup_run_after; ignoring the invalid schedule",
                    job.id,
                )
        complete_job(session, job, worker_id=worker_id)
        if status == "ok":
            _recover_account_sync_status(session, job)
        if not followup_was_scheduled and (followup or next_run_after):
            from mail_core.sync.jobs import enqueue_job

            next_payload = {k: v for k, v in payload.items() if not k.startswith("_followup_")}
            enqueue_job(
                session,
                job_type=job.job_type,
                account_id=job.account_id,
                payload=next_payload,
                priority=job.priority,
                run_after=next_run_after,
                dedupe_key=job.dedupe_key,
            )
        return True

    err_msg = str(result.get("error") or status or "job failed")
    log.warning("job %s (%s) returned non-ok status: %s", job.id, job.job_type, status)
    fail_job(session, job, f"{status}: {err_msg}", worker_id=worker_id)
    return False


def handle_job(session: Session, job: WorkerJob, *, worker_id: str | None = None) -> bool:
    """Dispatch. Sync handlers open their own short transactions + network I/O.

    Returns True when the job completed successfully, False when it was failed
    internally (``fail_job`` already applied). The claim transaction should be
    committed before heavy work; main.py commits after handle_job returns. The
    worker owns ``locked_at`` heartbeats; handlers must leave claim fields alone.
    """
    from mail_core.logging_config import trace_scope

    with trace_scope(f"job:{job.id.hex[:8]}"):
        return _handle_job_impl(session, job, worker_id=worker_id)


def _handle_job_impl(session: Session, job: WorkerJob, *, worker_id: str | None = None) -> bool:
    worker_id = worker_id or job.locked_by or "worker"
    payload = dict(job.payload or {})
    account_id = job.account_id

    try:
        if job.job_type in (
            JobType.SYNC_ACCOUNT_FOLDERS.value,
            JobType.SYNC_FOLDER_METADATA.value,
            JobType.SYNC_FOLDER_DELTA.value,
            JobType.RECONCILE_FOLDER.value,
        ):
            if account_id is None:
                log.info("job %s missing account_id, marking complete", job.id)
                complete_job(session, job, worker_id=worker_id)
                return True
            acc = session.get(Account, account_id)
            if acc is None or not acc.sync_enabled:
                log.info("account %s not found or sync disabled, skipping job %s", account_id, job.id)
                complete_job(session, job, worker_id=worker_id)
                return True

        if job.job_type == JobType.SYNC_ACCOUNT_FOLDERS.value:
            if account_id is None:
                raise ValueError("account_id required")
            # Commit claim TX before network-heavy engine work: caller commits;
            # engine uses separate sessions. We run engine after letting claim settle.
            from mail_core.sync.engine import sync_account_folders

            session.commit()
            result = sync_account_folders(account_id, worker_id=worker_id, store=get_credential_store())
            log.info("sync_account_folders %s", result)
            if result.get("status") in ("lease_busy", "provider_error"):
                update_account_sync_status(
                    session,
                    account_id,
                    SyncStatus.FAILED,
                    error=str(result.get("error") or result.get("status")),
                )
            return _evaluate_result(session, job, result, worker_id)

        if job.job_type == JobType.SYNC_FOLDER_METADATA.value:
            if account_id is None:
                raise ValueError("account_id required")
            folder_id = uuid.UUID(str(payload["folder_id"]))
            from mail_core.sync.engine import sync_folder_metadata

            session.commit()
            result = sync_folder_metadata(account_id, folder_id, worker_id=worker_id, store=get_credential_store())
            log.info("sync_folder_metadata %s", result)
            return _evaluate_result(session, job, result, worker_id)

        if job.job_type == JobType.RECONCILE_FOLDER.value:
            if account_id is None:
                raise ValueError("account_id required")
            folder_id = uuid.UUID(str(payload["folder_id"]))
            from mail_core.sync.reconcile import reconcile_folder

            session.commit()
            result = reconcile_folder(account_id, folder_id, worker_id=worker_id, store=get_credential_store())
            log.info("reconcile_folder %s", result)
            return _evaluate_result(session, job, result, worker_id)

        if job.job_type == JobType.REMOTE_OPERATION_PUSH.value:
            if account_id is None:
                raise ValueError("account_id required")
            from mail_core.sync.remote_push import push_remote_operations

            session.commit()
            result = push_remote_operations(account_id, worker_id=worker_id, store=get_credential_store())
            log.info("remote_operation_push %s", result)
            return _evaluate_result(session, job, result, worker_id)

        if job.job_type == JobType.ARCHIVE_MIME_BATCH.value:
            from mail_core.blobs.archive import run_archive_batch

            session.commit()
            result = run_archive_batch(
                account_id=account_id,
                worker_id=worker_id,
                store=get_credential_store(),
                payload=payload,
            )
            log.info("archive_mime_batch %s", result)
            return _evaluate_result(session, job, result, worker_id)

        if job.job_type == JobType.OUTBOX_DISPATCH_WAKE.value:
            # Worker must NOT mark_dispatched — that steals events from the API
            # process (no local SSE subscribers here). Only wake the API LISTEN.
            from mail_core.realtime.notify import try_notify_outbox

            try_notify_outbox(session)
            complete_job(session, job, worker_id=worker_id)
            log.info("outbox_dispatch_wake notified API listener")
            return True

        if job.job_type == JobType.SYNC_FOLDER_DELTA.value:
            if account_id is None:
                raise ValueError("account_id required")
            folder_id = uuid.UUID(str(payload["folder_id"]))
            from mail_core.sync.delta import sync_folder_delta

            session.commit()
            result = sync_folder_delta(
                account_id,
                folder_id,
                worker_id=worker_id,
                store=get_credential_store(),
                poll_round=int(payload.get("poll_round") or 0),
            )
            log.info("sync_folder_delta %s", result)
            return _evaluate_result(session, job, result, worker_id)

        if job.job_type == JobType.GC_BLOBS.value:
            from mail_core.blobs.archive import maybe_resume_quota_paused_archives
            from mail_core.blobs.gc import run_gc_blobs

            session.commit()
            hours = float(payload.get("cool_off_hours") or 24)
            result = run_gc_blobs(cool_off_hours=hours, dry_run=bool(payload.get("dry_run")))
            log.info("gc_blobs %s", result)
            if not payload.get("dry_run"):
                try:
                    maybe_resume_quota_paused_archives()
                except Exception as resume_exc:
                    log.warning("post-gc maybe_resume_quota_paused_archives error: %s", resume_exc)
            return _evaluate_result(session, job, result, worker_id)

        if job.job_type == JobType.BACKUP_RUN.value:
            from mail_core.backup.package import run_backup

            session.commit()
            result = run_backup(output_dir=payload.get("output_dir"))
            log.info("backup_run %s", result)
            return _evaluate_result(session, job, result, worker_id)

        fail_job(session, job, f"unknown job_type {job.job_type}", worker_id=worker_id)
        return False
    except Exception as exc:
        from mail_core.security.redact import safe_error
        from mail_core.providers.http import PermanentAuthError

        log.error("job %s (%s) failed: %s", job.id, job.job_type, safe_error(exc))
        log.debug("job %s traceback", job.id, exc_info=True)
        session.rollback()
        if account_id is not None and job.job_type in _ACCOUNT_SYNC_JOB_TYPES:
            try:
                status_label = SyncStatus.AUTH_FAILED if isinstance(exc, PermanentAuthError) else SyncStatus.FAILED
                update_account_sync_status(session, account_id, status_label, error=safe_error(exc))
                if isinstance(exc, PermanentAuthError):
                    acc = session.get(Account, account_id)
                    if acc:
                        acc.sync_enabled = False
                    session.commit()
            except Exception as status_exc:
                log.warning("failed to update account sync status for %s: %s", account_id, safe_error(status_exc))
                session.rollback()
        fail_job(session, job, exc, worker_id=worker_id)
        return False
