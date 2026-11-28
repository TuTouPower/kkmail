"""Tests for worker heartbeat, healthcheck CLI, and system health metrics."""

import json
import os
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
    # A385 semantic change (user decision, option A): the operational
    # metrics endpoints require authentication; only the /health
    # liveness probe (no sensitive fields) stays public. This replaces
    # the previous assertions that unauthenticated requests got 200.
    from mail_core.security.auth import reset_auth_caches
    from tests.mail_core.conftest import TEST_API_KEY

    reset_auth_caches()
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
    try:
        # Unauthenticated: metrics endpoints are closed, liveness is open.
        assert client.get("/api/system/health").status_code == 401
        assert client.get("/health/metrics").status_code == 401
        assert client.get("/health").status_code == 200

        headers = {"Authorization": f"Bearer {TEST_API_KEY}"}
        res = client.get("/api/system/health", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "healthy"
        assert data["worker"]["healthy"] is True
        assert data["worker"]["active_workers"] == ["worker-1"]

        res2 = client.get("/health/metrics", headers=headers)
        assert res2.status_code == 200
        assert res2.json()["status"] == "healthy"
    finally:
        reset_auth_caches()


def test_ready_endpoint_with_worker_flag(monkeypatch):
    """t095: /ready derives worker state from Core + liveness stamp (rewritten).

    The old test patched the ORM ``get_worker_heartbeats``; t095 reads worker
    state via ``read_worker_active_via_core`` (AUTOCOMMIT, no ROLLBACK) with a
    short TTL cache, so the patch seam moved there.
    """
    monkeypatch.setattr("mail_core.api.app._code_schema_head", lambda: "head-1")
    monkeypatch.setattr("mail_core.mail.storage.health.get_current_schema_revision", lambda: "head-1")
    monkeypatch.setattr("mail_core.readiness.get_readiness_probe", lambda: _FreshProbe())
    # read_worker_active_via_core is patched below; the engine arg is unused.
    monkeypatch.setattr("mail_core.db.session.get_engine", lambda *a, **k: object())

    class FakeListener:
        listen_ready = True

    monkeypatch.setattr("mail_core.realtime.listener.get_outbox_listener", lambda: FakeListener())

    # When worker is not running:
    monkeypatch.setattr(
        "mail_core.readiness.read_worker_active_via_core",
        lambda _engine: (False, None),
    )
    client = TestClient(app)
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json()["worker"] is False

    monkeypatch.setenv("MAIL_CORE_REQUIRE_WORKER_READY", "1")
    res_fail = client.get("/ready")
    assert res_fail.status_code == 503
    assert res_fail.json()["reason"] == "worker_not_running"

    # When worker is active:
    monkeypatch.setattr(
        "mail_core.readiness.read_worker_active_via_core",
        lambda _engine: (True, 5.0),
    )
    res_ok = client.get("/ready")
    assert res_ok.status_code == 200
    assert res_ok.json()["worker"] is True
    monkeypatch.delenv("MAIL_CORE_REQUIRE_WORKER_READY")


class _FreshProbe:
    """Readiness probe whose cache never serves a stale worker value."""

    def cached_worker_active(self):
        return None

    def snapshot(self, **_kwargs):
        return None


def test_worker_healthcheck_cli(monkeypatch, tmp_path):
    """t095: healthcheck verifies the liveness stamp (rewritten)."""
    from mail_core.liveness import write_liveness_stamp

    stamp = tmp_path / "liveness.json"
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(stamp))

    # Case 1: no stamp -> exit 1
    monkeypatch.delenv("MAIL_CORE_WORKER_ID", raising=False)
    assert healthcheck_main() == 1

    # Case 2: fresh stamp -> exit 0
    write_liveness_stamp(stamp, progress=1, worker_id="w1")
    assert healthcheck_main() == 0

    # Case 3: worker id in stamp does not gate a file-based probe.
    monkeypatch.setenv("MAIL_CORE_WORKER_ID", "w2")
    assert healthcheck_main() == 0
    monkeypatch.delenv("MAIL_CORE_WORKER_ID")

    # Case 4: stale stamp -> exit 1
    import os as _os

    _os.utime(stamp, (stamp.stat().st_atime, stamp.stat().st_mtime - 3600))
    monkeypatch.setenv("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG", "60")
    assert healthcheck_main() == 1


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_system_health_sync_metrics_with_real_sync_run_done_status():
    # A346 overall replacement: get_system_health_metrics now serves a
    # few-seconds in-process cache and the lag field is named
    # last_sync_lag_seconds, so this two-phase test clears the cache
    # between phases and asserts the renamed field (the old
    # max_sync_lag_seconds assertions described the pre-A346 contract).
    import uuid

    from mail_core.db.session import get_session_factory
    from mail_core.mail.domain.enums import SyncPhase, SyncRunStatus
    from mail_core.mail.storage.models import Account, SyncRun
    from mail_core.system_metrics import clear_system_health_cache

    Session = get_session_factory()
    with Session() as session:
        account = Account(
            id=uuid.uuid4(),
            email=f"metrics-{uuid.uuid4().hex[:6]}@example.com",
            provider="imap",
            sync_enabled=True,
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

        clear_system_health_cache()
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

        clear_system_health_cache()
        report_done = get_system_health_metrics(session)
        assert report_done.sync.last_sync_success_at is not None
        assert report_done.sync.last_sync_lag_seconds is not None
        assert report_done.sync.last_sync_lag_seconds >= 25.0
