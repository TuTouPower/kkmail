"""A346: system health metrics — cache, honest field name, honest status.

Old code: every call serially ran 6+ aggregate queries with no cache;
``SyncMetrics.max_sync_lag_seconds`` actually held "seconds since the
last successful sync *globally*" (not a per-account max); and the
``SystemHealthReport.status`` comment advertised ``"unhealthy"`` which
the code could never produce.

Fix: a few-seconds in-process TTL cache, the field renamed to
``last_sync_lag_seconds`` (old name kept as a read-only alias property),
and the status comment trimmed to the values actually produced.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import mail_core.system_metrics as metrics_mod
from mail_core.mail.storage.models import AppSetting
from mail_core.system_metrics import get_system_health_metrics


@pytest.fixture(autouse=True)
def _clear_cache():
    metrics_mod.clear_system_health_cache()
    yield
    metrics_mod.clear_system_health_cache()


def _mock_session(now: datetime) -> MagicMock:
    mock_session = MagicMock()
    fresh_time = now - timedelta(seconds=5)
    mock_session.scalars.return_value.all.return_value = [
        AppSetting(
            key="worker:heartbeat:worker-1",
            value=json.dumps({"worker_id": "worker-1", "updated_at": fresh_time.isoformat()}),
        )
    ]
    results = [
        MagicMock(one=lambda: (0, 0, 0, None)),
        MagicMock(one=lambda: (0, None)),
        MagicMock(one=lambda: (1, 1)),
        MagicMock(scalar=lambda: now - timedelta(seconds=90)),
    ]
    calls = {"n": 0}

    def _execute(_stmt):
        idx = calls["n"] % len(results)
        calls["n"] += 1
        return results[idx]

    mock_session.execute.side_effect = _execute
    mock_session.execute_calls = calls
    mock_session.get.return_value = None
    return mock_session


def test_sync_lag_field_renamed_to_last_sync_lag_seconds(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    report = get_system_health_metrics(_mock_session(now))
    assert report.sync.last_sync_lag_seconds is not None
    assert report.sync.last_sync_lag_seconds >= 89.0
    dumped = report.sync.model_dump()
    assert "last_sync_lag_seconds" in dumped
    assert "max_sync_lag_seconds" not in dumped
    # Read-only backwards-compatible alias.
    assert report.sync.max_sync_lag_seconds == report.sync.last_sync_lag_seconds


def test_metrics_are_cached_for_a_few_seconds(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    now = datetime.now(timezone.utc)
    session = _mock_session(now)
    first = get_system_health_metrics(session)
    calls_after_first = session.execute_calls["n"]
    assert calls_after_first == 4
    second = get_system_health_metrics(session)
    assert second is first
    assert session.execute_calls["n"] == calls_after_first


def test_metrics_cache_expires(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    monkeypatch.setattr(metrics_mod, "_CACHE_TTL_S", 0.0)
    now = datetime.now(timezone.utc)
    session = _mock_session(now)
    get_system_health_metrics(session)
    assert session.execute_calls["n"] == 4
    get_system_health_metrics(session)
    assert session.execute_calls["n"] == 8


def test_status_comment_no_longer_advertises_unhealthy():
    source = Path(metrics_mod.__file__).read_text(encoding="utf-8")
    status_line = next(
        line for line in source.splitlines() if re.search(r"status:\s*str\s*#", line)
    )
    assert "unhealthy" not in status_line
