"""Tests for worker heartbeat, healthcheck CLI, and system health metrics."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from mail_core.api.app import app
from mail_core.mail.storage.models import AppSetting
from mail_core.system_metrics import (
    BackupMetrics,
    JobMetrics,
    StorageMetrics,
    SyncMetrics,
    SystemHealthReport,
    WorkerMetrics,
    WritebackMetrics,
    get_system_health_metrics,
)
from mail_core.worker.healthcheck import main as healthcheck_main
from mail_core.worker.heartbeat import (
    cleanup_stale_heartbeats,
    get_worker_heartbeats,
    record_heartbeat,
)


def test_worker_heartbeat_record_and_get():
    mock_session = MagicMock()
    mock_session.get.return_value = None

    # Test record_heartbeat
    record_heartbeat(mock_session, "worker-test-1", active_jobs=3)
    assert mock_session.add.called
    added_obj = mock_session.add.call_args[0][0]
    assert isinstance(added_obj, AppSetting)
    assert added_obj.key == "worker:heartbeat:worker-test-1"
    data = json.loads(added_obj.value)
    assert data["worker_id"] == "worker-test-1"
    assert data["active_jobs"] == 3


def test_worker_heartbeat_query_active_and_stale():
    mock_session = MagicMock()
    now = datetime.now(timezone.utc)

    # 1 fresh, 1 stale
    fresh_time = now - timedelta(seconds=10)
    stale_time = now - timedelta(seconds=120)

    rows = [
        AppSetting(
            key="worker:heartbeat:worker-fresh",
            value=json.dumps({"worker_id": "worker-fresh", "updated_at": fresh_time.isoformat(), "pid": 100}),
        ),
        AppSetting(
            key="worker:heartbeat:worker-stale",
            value=json.dumps({"worker_id": "worker-stale", "updated_at": stale_time.isoformat(), "pid": 101}),
        ),
    ]
    mock_session.scalars.return_value.all.return_value = rows

    healthy, min_lag, active = get_worker_heartbeats(mock_session, stale_after_seconds=60.0)
    assert healthy is True
    assert min_lag is not None and 9.0 <= min_lag <= 15.0
    assert len(active) == 1
    assert active[0]["worker_id"] == "worker-fresh"


def test_worker_heartbeat_cleanup():
    mock_session = MagicMock()
    now = datetime.now(timezone.utc)
    stale_time = now - timedelta(seconds=90000)

    rows = [
        AppSetting(
            key="worker:heartbeat:worker-dead",
            value=json.dumps({"worker_id": "worker-dead", "updated_at": stale_time.isoformat()}),
        )
    ]
    mock_session.scalars.return_value.all.return_value = rows

    deleted = cleanup_stale_heartbeats(mock_session, older_than_seconds=86400.0)
    assert deleted == 1
    assert mock_session.execute.called


def test_system_health_metrics_calculation(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    mock_session = MagicMock()
    now = datetime.now(timezone.utc)

    # Mock heartbeats
    fresh_time = now - timedelta(seconds=5)
    mock_session.scalars.return_value.all.return_value = [
        AppSetting(
            key="worker:heartbeat:worker-1",
            value=json.dumps({"worker_id": "worker-1", "updated_at": fresh_time.isoformat()}),
        )
    ]

    # Mock SQL execution results
    mock_session.execute.side_effect = [
        # 1. job_counts: (pending, claimed, failed, min_run_after)
        MagicMock(one=lambda: (3, 1, 0, now - timedelta(seconds=20))),
        # 2. op_counts: (pending, min_created_at)
        MagicMock(one=lambda: (2, now - timedelta(seconds=15))),
        # 3. acc_counts: (total, active)
        MagicMock(one=lambda: (2, 2)),
        # 4. last_sync finished_at
        MagicMock(scalar=lambda: now - timedelta(seconds=60)),
    ]

    # Mock backup setting
    mock_session.get.return_value = AppSetting(
        key="backup:last_success",
        value=json.dumps({"finished_at": now.isoformat(), "status": "ok"}),
    )

    report = get_system_health_metrics(mock_session)

    assert report.status == "healthy"
    assert report.worker.healthy is True
    assert "worker-1" in report.worker.active_workers
    assert report.jobs.pending_count == 3
    assert report.jobs.claimed_count == 1
    assert report.jobs.failed_count == 0
    assert report.jobs.oldest_pending_seconds is not None and report.jobs.oldest_pending_seconds >= 19.0
    assert report.writeback.pending_count == 2
    assert report.writeback.oldest_pending_seconds is not None and report.writeback.oldest_pending_seconds >= 14.0
    assert report.sync.total_accounts == 2
    assert report.sync.active_accounts == 2
    assert report.sync.last_sync_success_at is not None
    assert report.storage.total_bytes is not None
    assert report.backup.last_backup_status == "ok"


def test_api_system_health_endpoint(monkeypatch):
    mock_session = MagicMock()
    monkeypatch.setattr("mail_core.db.session.get_session_factory", lambda: lambda: mock_session)
    mock_report = SystemHealthReport(
        status="healthy",
        worker=WorkerMetrics(healthy=True, lag_seconds=2.5, active_workers=["worker-1"]),
        jobs=JobMetrics(pending_count=0, claimed_count=0, failed_count=0),
        writeback=WritebackMetrics(pending_count=0),
        sync=SyncMetrics(total_accounts=1, active_accounts=1),
        storage=StorageMetrics(total_bytes=1000, free_bytes=500, used_percent=50.0),
        backup=BackupMetrics(last_backup_status="ok"),
    )
    monkeypatch.setattr("mail_core.system_metrics.get_system_health_metrics", lambda _session: mock_report)

    client = TestClient(app)
    res = client.get("/api/system/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "healthy"
    assert data["worker"]["healthy"] is True
    assert data["worker"]["active_workers"] == ["worker-1"]

    res2 = client.get("/health/metrics")
    assert res2.status_code == 200
    assert res2.json()["status"] == "healthy"


def test_ready_endpoint_with_worker_flag(monkeypatch):
    mock_session = MagicMock()
    monkeypatch.setattr("mail_core.db.session.get_session_factory", lambda: lambda: mock_session)
    monkeypatch.setattr("mail_core.api.app._code_schema_head", lambda: "head-1")
    monkeypatch.setattr("mail_core.mail.storage.health.get_current_schema_revision", lambda: "head-1")

    class FakeListener:
        listen_ready = True

    monkeypatch.setattr("mail_core.realtime.listener.get_outbox_listener", lambda: FakeListener())

    # When worker is not running:
    monkeypatch.setattr(
        "mail_core.worker.heartbeat.get_worker_heartbeats",
        lambda _session: (False, None, []),
    )

    client = TestClient(app)
    # Default require_worker not set -> returns 200, worker=False
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json()["worker"] is False

    # When MAIL_CORE_REQUIRE_WORKER_READY=1 -> returns 503
    monkeypatch.setenv("MAIL_CORE_REQUIRE_WORKER_READY", "1")
    res_fail = client.get("/ready")
    assert res_fail.status_code == 503
    assert res_fail.json()["reason"] == "worker_not_running"

    # When worker is active -> returns 200, worker=True
    monkeypatch.setattr(
        "mail_core.worker.heartbeat.get_worker_heartbeats",
        lambda _session: (True, 5.0, [{"worker_id": "worker-1"}]),
    )
    res_ok = client.get("/ready")
    assert res_ok.status_code == 200
    assert res_ok.json()["worker"] is True


def test_worker_healthcheck_cli(monkeypatch):
    mock_session = MagicMock()
    monkeypatch.setattr("mail_core.worker.healthcheck.get_session_factory", lambda: lambda: mock_session)

    # Case 1: no active workers -> exit 1
    monkeypatch.setattr(
        "mail_core.worker.healthcheck.get_worker_heartbeats",
        lambda _session, **_kwargs: (False, None, []),
    )
    assert healthcheck_main() == 1

    # Case 2: active workers -> exit 0
    monkeypatch.setattr(
        "mail_core.worker.healthcheck.get_worker_heartbeats",
        lambda _session, **_kwargs: (True, 2.0, [{"worker_id": "w1", "active": True, "lag_seconds": 2.0}]),
    )
    assert healthcheck_main() == 0

    # Case 3: specific worker ID matching
    monkeypatch.setenv("MAIL_CORE_WORKER_ID", "w1")
    assert healthcheck_main() == 0

    # Case 4: specific worker ID not matching
    monkeypatch.setenv("MAIL_CORE_WORKER_ID", "w2")
    assert healthcheck_main() == 1


def test_system_health_sync_metrics_with_real_sync_run_done_status():
    import uuid
    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import SyncPhase, SyncRunStatus
    from mail_core.mail.storage.models import Account, SyncRun

    Session = get_session_factory()
    with Session() as session:
        account = Account(
            id=uuid.uuid4(),
            email=f"metrics-{uuid.uuid4().hex[:6]}@example.com",
            provider="imap",
            sync_enabled=True,
            sync_status="idle",
        )
        session.add(account)
        session.flush()

        # Insert a RUNNING sync run first
        running_run = SyncRun(
            id=uuid.uuid4(),
            account_id=account.id,
            status=SyncRunStatus.RUNNING.value,
            phase=SyncPhase.FOLDER_DISCOVERY.value,
            started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        session.add(running_run)
        session.flush()

        report_running = get_system_health_metrics(session)
        assert report_running.sync.last_sync_success_at is None

        # Insert a DONE sync run
        finished_time = datetime.now(timezone.utc) - timedelta(seconds=30)
        done_run = SyncRun(
            id=uuid.uuid4(),
            account_id=account.id,
            status=SyncRunStatus.DONE.value,
            phase=SyncPhase.INCREMENTAL_READY.value,
            started_at=finished_time - timedelta(minutes=1),
            finished_at=finished_time,
        )
        session.add(done_run)
        session.flush()

        report_done = get_system_health_metrics(session)
        assert report_done.sync.last_sync_success_at is not None
        assert report_done.sync.max_sync_lag_seconds is not None
        assert report_done.sync.max_sync_lag_seconds >= 25.0
