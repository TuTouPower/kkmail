"""System-level operational and business health metrics aggregator."""

from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import (
    Account,
    AppSetting,
    RemoteOperation,
    SyncRun,
    WorkerJob,
)
from mail_core.worker.heartbeat import get_worker_heartbeats

log = logging.getLogger("mail_core.system_metrics")


class WorkerMetrics(BaseModel):
    healthy: bool
    lag_seconds: float | None = None
    active_workers: list[str] = Field(default_factory=list)


class JobMetrics(BaseModel):
    pending_count: int = 0
    claimed_count: int = 0
    failed_count: int = 0
    oldest_pending_seconds: float | None = None


class WritebackMetrics(BaseModel):
    pending_count: int = 0
    oldest_pending_seconds: float | None = None


class SyncMetrics(BaseModel):
    total_accounts: int = 0
    active_accounts: int = 0
    last_sync_success_at: str | None = None
    max_sync_lag_seconds: float | None = None


class StorageMetrics(BaseModel):
    total_bytes: int | None = None
    free_bytes: int | None = None
    used_percent: float | None = None


class BackupMetrics(BaseModel):
    last_backup_at: str | None = None
    last_backup_status: str | None = None


class SystemHealthReport(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    worker: WorkerMetrics
    jobs: JobMetrics
    writeback: WritebackMetrics
    sync: SyncMetrics
    storage: StorageMetrics
    backup: BackupMetrics


def get_system_health_metrics(session: Session) -> SystemHealthReport:
    """Collect lightweight aggregated operational and business health metrics."""
    now = datetime.now(timezone.utc)

    # 1. Worker heartbeats
    worker_healthy, worker_lag, active_worker_dicts = get_worker_heartbeats(session)
    active_ids = [w.get("worker_id") for w in active_worker_dicts if w.get("worker_id")]
    worker_metric = WorkerMetrics(
        healthy=worker_healthy,
        lag_seconds=worker_lag,
        active_workers=active_ids,
    )

    # 2. Worker jobs
    job_counts = session.execute(
        select(
            func.count().filter(WorkerJob.status == "pending"),
            func.count().filter(WorkerJob.status == "claimed"),
            func.count().filter(WorkerJob.status == "failed"),
            func.min(WorkerJob.run_after).filter(WorkerJob.status == "pending"),
        )
    ).one()
    pending_jobs, claimed_jobs, failed_jobs, oldest_job_run_after = job_counts

    oldest_job_lag: float | None = None
    if oldest_job_run_after is not None:
        diff = (now - oldest_job_run_after).total_seconds()
        oldest_job_lag = round(max(0.0, diff), 2)

    jobs_metric = JobMetrics(
        pending_count=int(pending_jobs or 0),
        claimed_count=int(claimed_jobs or 0),
        failed_count=int(failed_jobs or 0),
        oldest_pending_seconds=oldest_job_lag,
    )

    # 3. Writeback operations
    op_counts = session.execute(
        select(
            func.count().filter(RemoteOperation.status == "pending"),
            func.min(RemoteOperation.created_at).filter(RemoteOperation.status == "pending"),
        )
    ).one()
    pending_ops, oldest_op_created_at = op_counts

    oldest_op_lag: float | None = None
    if oldest_op_created_at is not None:
        diff = (now - oldest_op_created_at).total_seconds()
        oldest_op_lag = round(max(0.0, diff), 2)

    writeback_metric = WritebackMetrics(
        pending_count=int(pending_ops or 0),
        oldest_pending_seconds=oldest_op_lag,
    )

    # 4. Sync metrics
    acc_counts = session.execute(
        select(
            func.count(),
            func.count().filter(Account.sync_enabled.is_(True)),
        ).select_from(Account)
    ).one()
    total_accs, active_accs = acc_counts

    last_sync = session.execute(
        select(func.max(SyncRun.finished_at)).where(SyncRun.status == "success")
    ).scalar()

    last_sync_iso: str | None = None
    sync_lag: float | None = None
    if last_sync is not None:
        last_sync_iso = last_sync.isoformat()
        sync_lag = round(max(0.0, (now - last_sync).total_seconds()), 2)

    sync_metric = SyncMetrics(
        total_accounts=int(total_accs or 0),
        active_accounts=int(active_accs or 0),
        last_sync_success_at=last_sync_iso,
        max_sync_lag_seconds=sync_lag,
    )

    # 5. Storage metrics
    blob_root = os.environ.get("MAIL_CORE_BLOB_ROOT", "")
    storage_metric = StorageMetrics()
    if blob_root and os.path.exists(blob_root):
        try:
            usage = shutil.disk_usage(blob_root)
            total = usage.total
            free = usage.free
            used_pct = round((usage.used / total) * 100, 2) if total > 0 else 0.0
            storage_metric = StorageMetrics(
                total_bytes=total,
                free_bytes=free,
                used_percent=used_pct,
            )
        except Exception as exc:
            log.warning("failed to check disk usage at %s: %s", blob_root, exc)

    # 6. Backup metrics
    backup_row = session.get(AppSetting, "backup:last_success")
    backup_metric = BackupMetrics()
    if backup_row:
        try:
            bdata = json.loads(backup_row.value)
            backup_metric = BackupMetrics(
                last_backup_at=bdata.get("finished_at"),
                last_backup_status=bdata.get("status", "ok"),
            )
        except Exception:
            backup_metric = BackupMetrics(last_backup_status="unreadable")

    # Determine overall status
    is_degraded = False
    if not worker_healthy and int(active_accs or 0) > 0:
        is_degraded = True
    if storage_metric.free_bytes is not None and storage_metric.free_bytes < 500 * 1024 * 1024:
        # Less than 500MB free disk
        is_degraded = True
    if jobs_metric.failed_count > 20:
        is_degraded = True

    status = "degraded" if is_degraded else "healthy"

    return SystemHealthReport(
        status=status,
        worker=worker_metric,
        jobs=jobs_metric,
        writeback=writeback_metric,
        sync=sync_metric,
        storage=storage_metric,
        backup=backup_metric,
    )
