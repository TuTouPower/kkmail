"""A295: heartbeat read path must not silently skip corrupt/naive rows.

- Naive timestamps are interpreted as UTC in both get and cleanup.
- Corrupt rows are counted and warned about on the get side (not silent).
- Cleanup uses the same parsing policy: a fresh naive row survives, an
  old naive row and corrupt rows are removed.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from mail_core.mail.storage.models import AppSetting
from mail_core.worker.heartbeat import cleanup_stale_heartbeats, get_worker_heartbeats


def _session_with(rows):
    session = MagicMock()
    session.scalars.return_value.all.return_value = rows
    return session


def _row(key, value):
    return AppSetting(key=key, value=value)


def test_naive_fresh_timestamp_counts_as_active():
    naive = (datetime.now(timezone.utc) - timedelta(seconds=5)).replace(tzinfo=None)
    rows = [_row("worker:heartbeat:w1", json.dumps({"worker_id": "w1", "updated_at": naive.isoformat()}))]
    healthy, lag, active = get_worker_heartbeats(_session_with(rows), stale_after_seconds=60.0)
    assert healthy is True
    assert len(active) == 1
    assert lag is not None


def test_corrupt_row_warns_and_is_skipped(caplog):
    now = datetime.now(timezone.utc)
    rows = [
        _row("worker:heartbeat:bad", "not-json{{{"),
        _row(
            "worker:heartbeat:w1",
            json.dumps({"worker_id": "w1", "updated_at": now.isoformat()}),
        ),
    ]
    with caplog.at_level(logging.WARNING, logger="mail_core.worker.heartbeat"):
        healthy, _lag, active = get_worker_heartbeats(_session_with(rows), stale_after_seconds=60.0)
    assert healthy is True
    assert len(active) == 1
    assert "heartbeat" in caplog.text.lower()


def test_cleanup_keeps_fresh_naive_row():
    naive_fresh = (datetime.now(timezone.utc) - timedelta(seconds=30)).replace(tzinfo=None)
    rows = [_row("worker:heartbeat:w1", json.dumps({"worker_id": "w1", "updated_at": naive_fresh.isoformat()}))]
    session = _session_with(rows)
    deleted = cleanup_stale_heartbeats(session, older_than_seconds=86400.0)
    assert deleted == 0


def test_cleanup_deletes_old_naive_and_corrupt_rows():
    naive_old = (datetime.now(timezone.utc) - timedelta(seconds=90000)).replace(tzinfo=None)
    rows = [
        _row("worker:heartbeat:old", json.dumps({"worker_id": "old", "updated_at": naive_old.isoformat()})),
        _row("worker:heartbeat:bad", "not-json{{{"),
    ]
    session = _session_with(rows)
    deleted = cleanup_stale_heartbeats(session, older_than_seconds=86400.0)
    assert deleted == 2
