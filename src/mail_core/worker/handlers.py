"""Job dispatch table for the worker process."""

from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.accounts.credentials import get_credential_store
from mail_core.accounts.service import update_account_sync_status
from mail_core.mail.domain.enums import JobStatus, JobType, SyncStatus
from mail_core.mail.storage.models import Account, WorkerJob
from mail_core.providers.connection_slots import (
    CAPACITY_RETRY_SECONDS,
    is_capacity_error,
    traffic_class_for_job,
)
from mail_core.sync.jobs import complete_job, fail_job, reschedule_job

log = logging.getLogger("mail_core.worker.handlers")
_ACCOUNT_SYNC_JOB_TYPES = (
    JobType.SYNC_ACCOUNT_FOLDERS.value,
    JobType.SYNC_FOLDER_METADATA.value,
    JobType.SYNC_FOLDER_DELTA.value,
    JobType.RECONCILE_FOLDER.value,
)
_FOLDER_SYNC_JOB_TYPES = (
    JobType.SYNC_FOLDER_METADATA.value,
    JobType.SYNC_FOLDER_DELTA.value,
    JobType.RECONCILE_FOLDER.value,
)
_RESULT_LOG_COUNT_KEYS = (
    "actions",
    "claimed",
    "completed",
    "deleted",
    "failed",
    "flagged",
    "folders",
    "pages",
    "pushed",
    "upserted",
    "used_bytes",
)
_RESULT_LOG_DURATION_KEYS = ("duration_s", "duration_seconds")


def _result_log_summary(result: dict[str, Any]) -> dict[str, str | int | float]:
    summary: dict[str, str | int | float] = {}
    status = result.get("status")
    if isinstance(status, str):
        summary["status"] = status
    for key in _RESULT_LOG_COUNT_KEYS:
        value = result.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            summary[key] = value
    for key in _RESULT_LOG_DURATION_KEYS:
        value = result.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            summary[key] = value
    return summary


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _coerce_retry_after(value: Any, *, fallback: float = CAPACITY_RETRY_SECONDS) -> float:
    """Coerce a capacity ``retry_after`` hint to a usable delay (A18).

    Handler results and provider exceptions carry this value across
    loosely-typed boundaries, so it may be a non-numeric string, NaN or
    infinity. Anything that is not a finite, non-negative number falls
    back to the default capacity delay instead of raising — a bare
    ``float(...)`` failure here would turn a no-attempt deferral into a
    counted job failure.
    """
    if isinstance(value, bool):
        return fallback
    try:
        delay = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    if not math.isfinite(delay) or delay < 0:
        return fallback
    return delay


def _validate_job_payload(job: WorkerJob) -> tuple[dict[str, Any], str | None]:
    if job.payload is None:
        payload: dict[str, Any] = {}
    elif isinstance(job.payload, dict):
        payload = dict(job.payload)
    else:
        return {}, "payload must be an object"

    if job.job_type in _FOLDER_SYNC_JOB_TYPES:
        folder_id = payload.get("folder_id")
        if not isinstance(folder_id, str) or not folder_id.strip():
            return payload, "folder_id is required"
        try:
            uuid.UUID(folder_id)
        except ValueError:
            return payload, "folder_id must be a UUID"

    if job.job_type == JobType.SYNC_FOLDER_DELTA.value:
        poll_round = payload.get("poll_round")
        if poll_round not in (None, ""):
            if isinstance(poll_round, bool) or not isinstance(poll_round, (int, str)):
                return payload, "poll_round must be an integer"
            try:
                int(poll_round)
            except ValueError:
                return payload, "poll_round must be an integer"

    if job.job_type == JobType.GC_BLOBS.value:
        cool_off_hours = payload.get("cool_off_hours")
        if cool_off_hours not in (None, ""):
            # A253: the handler converts this with float(); reject
            # non-numeric / non-finite / negative values here instead of
            # letting the conversion raise (counted failure) or letting
            # a negative cool-off make nearly every blob GC-eligible.
            if isinstance(cool_off_hours, bool) or not isinstance(cool_off_hours, (int, float, str)):
                return payload, "cool_off_hours must be a finite number >= 0"
            try:
                cool_off_value = float(cool_off_hours)
            except ValueError:
                return payload, "cool_off_hours must be a finite number >= 0"
            if not math.isfinite(cool_off_value) or cool_off_value < 0:
                return payload, "cool_off_hours must be a finite number >= 0"

    if job.job_type == JobType.BACKUP_RUN.value:
        output_dir = payload.get("output_dir")
        if output_dir is not None and not isinstance(output_dir, str):
            return payload, "output_dir must be a string"
    return payload, None


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
    if status == "capacity_unavailable":
        # Connection-budget deferral (design §7): never a business
        # failure, never an account sync/auth failure.  Either the
        # handler already enqueued a delayed followup (then completing
        # this job is correct) or the current job itself is rescheduled
        # without counting an attempt.
        if result.get("followup_scheduled"):
            complete_job(session, job, worker_id=worker_id, result=result)
            return True
        delay = result.get("retry_after")
        reschedule_job(
            session,
            job,
            worker_id=worker_id,
            delay_seconds=_coerce_retry_after(delay),
        )
        return False
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
        complete_job(session, job, worker_id=worker_id, result=result)
        if status == "ok":
            _recover_account_sync_status(session, job)
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
    payload, invalid_payload = _validate_job_payload(job)
    if invalid_payload is not None:
        log.warning("job %s (%s) has invalid_payload: %s", job.id, job.job_type, invalid_payload)
        fail_job(
            session,
            job,
            f"invalid_payload: {invalid_payload}",
            worker_id=worker_id,
            max_attempts=1,
        )
        return False
    account_id = job.account_id
    # Explicit traffic class from the actual job type (+ message_id for
    # archive jobs), propagated into provider construction (design §7).
    traffic_class = traffic_class_for_job(job.job_type, payload=payload)

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
            result = sync_account_folders(
                account_id,
                worker_id=worker_id,
                store=get_credential_store(),
                traffic_class=traffic_class,
                full=bool(payload.get("full")),
                scan_generation=_uuid_or_none(payload.get("scan_generation")),
                request_id=_uuid_or_none(payload.get("request_id")),
            )
            log.info("sync_account_folders %s", _result_log_summary(result))
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
            result = sync_folder_metadata(
                account_id,
                folder_id,
                worker_id=worker_id,
                store=get_credential_store(),
                traffic_class=traffic_class,
                full=bool(payload.get("full")),
                scan_generation=_uuid_or_none(payload.get("scan_generation")),
                request_id=_uuid_or_none(payload.get("request_id")),
            )
            log.info("sync_folder_metadata %s", _result_log_summary(result))
            return _evaluate_result(session, job, result, worker_id)

        if job.job_type == JobType.RECONCILE_FOLDER.value:
            if account_id is None:
                raise ValueError("account_id required")
            folder_id = uuid.UUID(str(payload["folder_id"]))
            from mail_core.sync.reconcile import reconcile_folder

            session.commit()
            result = reconcile_folder(account_id, folder_id, worker_id=worker_id, store=get_credential_store(), traffic_class=traffic_class)
            log.info("reconcile_folder %s", _result_log_summary(result))
            return _evaluate_result(session, job, result, worker_id)

        if job.job_type == JobType.REMOTE_OPERATION_PUSH.value:
            if account_id is None:
                raise ValueError("account_id required")
            from mail_core.sync.remote_push import push_remote_operations

            session.commit()
            result = push_remote_operations(account_id, worker_id=worker_id, store=get_credential_store(), traffic_class=traffic_class)
            log.info("remote_operation_push %s", _result_log_summary(result))
            return _evaluate_result(session, job, result, worker_id)

        if job.job_type == JobType.ARCHIVE_MIME_BATCH.value:
            from mail_core.blobs.archive import run_archive_batch

            session.commit()
            result = run_archive_batch(
                account_id=account_id,
                worker_id=worker_id,
                store=get_credential_store(),
                payload=payload,
                traffic_class=traffic_class,
            )
            log.info("archive_mime_batch %s", _result_log_summary(result))
            return _evaluate_result(session, job, result, worker_id)

        if job.job_type == JobType.OUTBOX_DISPATCH_WAKE.value:
            # Worker must NOT dispatch — fan-out is owned by the API process
            # (no local SSE subscribers here). Only wake the API LISTEN.
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
                traffic_class=traffic_class,
                poll_round=int(payload.get("poll_round") or 0),
            )
            log.info("sync_folder_delta %s", _result_log_summary(result))
            return _evaluate_result(session, job, result, worker_id)

        if job.job_type == JobType.GC_BLOBS.value:
            from mail_core.blobs.archive import maybe_resume_quota_paused_archives
            from mail_core.blobs.gc import run_gc_blobs

            session.commit()
            hours = float(payload.get("cool_off_hours") or 24)
            result = run_gc_blobs(cool_off_hours=hours, dry_run=bool(payload.get("dry_run")))
            log.info("gc_blobs %s", _result_log_summary(result))
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
            log.info("backup_run %s", _result_log_summary(result))
            return _evaluate_result(session, job, result, worker_id)

        fail_job(session, job, f"unknown job_type {job.job_type}", worker_id=worker_id)
        return False
    except Exception as exc:
        from mail_core.security.redact import safe_error
        from mail_core.providers.http import PermanentAuthError

        if is_capacity_error(exc):
            # Budget/control deferral: reschedule without counting a
            # failure and without touching account sync/auth status.
            log.info("job %s (%s) deferred: provider connection capacity", job.id, job.job_type)
            session.rollback()
            reschedule_job(
                session,
                job,
                worker_id=worker_id,
                delay_seconds=_coerce_retry_after(getattr(exc, "retry_after_seconds", None)),
            )
            return False
        log.error("job %s (%s) failed: %s", job.id, job.job_type, safe_error(exc))
        log.debug("job %s traceback", job.id, exc_info=True)
        session.rollback()

        is_auth_error = isinstance(exc, PermanentAuthError)
        is_transient_network = (
            isinstance(exc, (TimeoutError, ConnectionError, OSError))
            or "ssl" in type(exc).__name__.lower()
            or "eof" in type(exc).__name__.lower()
        )
        from mail_core.sync.jobs import _max_attempts
        curr_failure_attempts = int(getattr(job, "failure_attempts", 0) or 0)
        is_terminal = (curr_failure_attempts + 1) >= _max_attempts()
        should_mark_account_failed = is_auth_error or (is_terminal and not is_transient_network)

        if account_id is not None and job.job_type in _ACCOUNT_SYNC_JOB_TYPES and should_mark_account_failed:
            try:
                status_label = SyncStatus.AUTH_FAILED if is_auth_error else SyncStatus.FAILED
                update_account_sync_status(session, account_id, status_label, error=safe_error(exc))
                if is_auth_error:
                    acc = session.get(Account, account_id)
                    if acc:
                        acc.sync_enabled = False
                    session.commit()
            except Exception as status_exc:
                log.warning("failed to update account sync status for %s: %s", account_id, safe_error(status_exc))
                session.rollback()
        fail_job(session, job, exc, worker_id=worker_id)
        return False
