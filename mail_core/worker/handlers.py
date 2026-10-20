"""Job dispatch table for the worker process."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from mail_core.mail.storage.models import WorkerJob
from mail_core.sync.jobs import complete_job, fail_job

log = logging.getLogger("mail_core.worker.handlers")


def handle_job(session: Session, job: WorkerJob) -> None:
    # Concrete sync/archive handlers land in later milestones.
    if job.job_type in {
        "sync_account_folders",
        "sync_folder_metadata",
        "sync_folder_delta",
        "reconcile_folder",
        "remote_operation_push",
        "archive_mime_batch",
        "outbox_dispatch_wake",
        "gc_blobs",
        "backup_run",
    }:
        log.info("noop handler for %s id=%s", job.job_type, job.id)
        complete_job(session, job)
        return
    fail_job(session, job, f"unknown job_type {job.job_type}")
