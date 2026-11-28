"""A294 + t095: healthcheck env parsing + sanitized error output.

The probe no longer queries PostgreSQL; it verifies the worker's filesystem
liveness stamp. The env-parsing and error-sanitization contract (A294) is
preserved: an invalid MAX_LAG returns 1 without a raw traceback, and an
unexpected backend error never leaks its message to stderr.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mail_core.worker import healthcheck
from mail_core.worker.healthcheck import main as healthcheck_main


@pytest.fixture(autouse=True)
def _mock_stamp(monkeypatch, tmp_path):
    stamp_file = tmp_path / "liveness.json"
    stamp_file.write_text('{"progress": 1, "worker_id": "w1", "v": 1}')
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(stamp_file))
    monkeypatch.delenv("MAIL_CORE_WORKER_ID", raising=False)


@pytest.mark.parametrize("raw", ["not-a-number", "nan", "inf", "-inf", "-5", "0"])
def test_invalid_max_lag_returns_1_without_traceback_or_raw_exc(monkeypatch, capsys, raw):
    monkeypatch.setenv("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG", raw)
    assert healthcheck_main() == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert "ValueError" in err
    assert "could not convert" not in err


def test_valid_max_lag_still_healthy(monkeypatch, capsys):
    monkeypatch.setenv("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG", "30")
    assert healthcheck_main() == 0


def test_backend_error_prints_type_name_only(monkeypatch, capsys):
    secret_detail = "postgresql://user:hunter2@db.internal:5432/kkmail"

    def boom(*_args, **_kw):
        raise RuntimeError(f"connection failed: {secret_detail}")

    monkeypatch.setattr("mail_core.worker.healthcheck.read_liveness_stamp", boom)
    monkeypatch.delenv("MAIL_CORE_WORKER_HEALTHCHECK_MAX_LAG", raising=False)
    assert healthcheck_main() == 1
    err = capsys.readouterr().err
    assert "RuntimeError" in err
    assert secret_detail not in err
    assert "hunter2" not in err
    assert "connection failed" not in err
