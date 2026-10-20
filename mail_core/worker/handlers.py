"""Job dispatch table for the worker process."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from mail_core.accounts.credentials import get_credential_store
from mail_core.mail.domain.enums import JobType
from mail_core.mail.storage.models import WorkerJob
from mail_core.sync.jobs import complete_job, fail_job

log = logging.getLogger("mail_core.worker.handlers")


def handle_job(session: Session, job: WorkerJob) -> None:
    """Dispatch. Sync handlers open their own short transactions + network I/O.

    The claim transaction should be committed before heavy work; main.py commits
    after handle_job returns. Sync engines manage their own sessions, so we mark
    the job complete here after the engine returns.
    """
    worker_id = job.locked_by or "worker"
    payload = dict(job.payload or {})
    account_id = job.account_id
    store = get_credential_store()

    try:
        if job.job_type == JobType.SYNC_ACCOUNT_FOLDERS.value:
            if account_id is None:
                raise ValueError("account_id required")
            # Commit claim TX before network-heavy engine work: caller commits;
            # engine uses separate sessions. We run engine after letting claim settle.
            from mail_core.sync.engine import sync_account_folders

            session.commit()
            result = sync_account_folders(account_id, worker_id=worker_id, store=store)
            log.info("sync_account_folders %s", result)
            complete_job(session, job)
            return

        if job.job_type == JobType.SYNC_FOLDER_METADATA.value:
            if account_id is None:
                raise ValueError("account_id required")
            folder_id = uuid.UUID(str(payload["folder_id"]))
            from mail_core.sync.engine import sync_folder_metadata

            session.commit()
            result = sync_folder_metadata(account_id, folder_id, worker_id=worker_id, store=store)
            log.info("sync_folder_metadata %s", result)
            complete_job(session, job)
            return

        if job.job_type == JobType.RECONCILE_FOLDER.value:
            if account_id is None:
                raise ValueError("account_id required")
            folder_id = uuid.UUID(str(payload["folder_id"]))
            from mail_core.sync.reconcile import reconcile_folder

            session.commit()
            result = reconcile_folder(account_id, folder_id, worker_id=worker_id, store=store)
            log.info("reconcile_folder %s", result)
            complete_job(session, job)
            return

        if job.job_type == JobType.REMOTE_OPERATION_PUSH.value:
            if account_id is None:
                raise ValueError("account_id required")
            from mail_core.sync.remote_push import push_remote_operations

            session.commit()
            result = push_remote_operations(account_id, worker_id=worker_id, store=store)
            log.info("remote_operation_push %s", result)
            complete_job(session, job)
            return

        if job.job_type == JobType.ARCHIVE_MIME_BATCH.value:
            from mail_core.blobs.archive import run_archive_batch

            session.commit()
            result = run_archive_batch(
                account_id=account_id,
                worker_id=worker_id,
                store=store,
                payload=payload,
            )
            log.info("archive_mime_batch %s", result)
            complete_job(session, job)
            return

        if job.job_type == JobType.OUTBOX_DISPATCH_WAKE.value:
            from mail_core.realtime.dispatcher import get_dispatcher

            session.commit()
            n = get_dispatcher().dispatch_once()
            log.info("outbox_dispatch_wake dispatched=%s", n)
            complete_job(session, job)
            return

        if job.job_type == JobType.SYNC_FOLDER_DELTA.value:
            if account_id is None:
                raise ValueError("account_id required")
            folder_id = uuid.UUID(str(payload["folder_id"]))
            from mail_core.sync.delta import sync_folder_delta

            session.commit()
            result = sync_folder_delta(account_id, folder_id, worker_id=worker_id, store=store)
            log.info("sync_folder_delta %s", result)
            complete_job(session, job)
            return

        if job.job_type == JobType.GC_BLOBS.value:
            from mail_core.blobs.gc import run_gc_blobs

            session.commit()
            hours = float(payload.get("cool_off_hours") or 24)
            result = run_gc_blobs(cool_off_hours=hours, dry_run=bool(payload.get("dry_run")))
            log.info("gc_blobs %s", result)
            complete_job(session, job)
            return

        if job.job_type == JobType.BACKUP_RUN.value:
            from mail_core.backup.package import run_backup

            session.commit()
            result = run_backup(output_dir=payload.get("output_dir"))
            log.info("backup_run %s", result)
            complete_job(session, job)
            return

        fail_job(session, job, f"unknown job_type {job.job_type}")
    except Exception as exc:
        log.exception("job %s failed", job.id)
        session.rollback()
        fail_job(session, job, str(exc))
