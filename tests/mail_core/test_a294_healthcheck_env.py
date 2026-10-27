"""A294: healthcheck env parsing + sanitized error output.

Old code parsed ``float(os.environ[...])`` *outside* the try block, so
an invalid MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG crashed with a raw
traceback, and the except branch printed the full exception message
(DB errors can embed connection details) to stderr.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mail_core.worker import healthcheck
from mail_core.worker.healthcheck import main as healthcheck_main


@pytest.fixture(autouse=True)
def _mock_session(monkeypatch):
    mock_session = MagicMock()
    monkeypatch.setattr(
        "mail_core.worker.healthcheck.get_session_factory", lambda: lambda: mock_session
    )
    monkeypatch.setattr(
        "mail_core.worker.healthcheck.get_worker_heartbeats",
        lambda _session, **_kw: (True, 1.0, [{"worker_id": "w1", "active": True}]),
    )
    monkeypatch.delenv("MAIL_CORE_WORKER_ID", raising=False)


@pytest.mark.parametrize("raw", ["not-a-number", "nan", "inf", "-inf", "-5", "0"])
def test_invalid_max_lag_returns_1_without_traceback_or_raw_exc(monkeypatch, capsys, raw):
    monkeypatch.setenv("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG", raw)
    assert healthcheck_main() == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "ValueError" in err
    # Only the type name: the raw float() message must not be printed.
    assert "could not convert" not in err


def test_valid_max_lag_still_healthy(monkeypatch, capsys):
    monkeypatch.setenv("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG", "30")
    assert healthcheck_main() == 0


def test_backend_error_prints_type_name_only(monkeypatch, capsys):
    secret_detail = "postgresql://user:hunter2@db.internal:5432/kkmail"

    def boom(_session, **_kw):
        raise RuntimeError(f"connection failed: {secret_detail}")

    monkeypatch.setattr("mail_core.worker.healthcheck.get_worker_heartbeats", boom)
    monkeypatch.delenv("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG", raising=False)
    assert healthcheck_main() == 1
    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert secret_detail not in err
    assert "hunter2" not in err
    assert "connection failed" not in err
