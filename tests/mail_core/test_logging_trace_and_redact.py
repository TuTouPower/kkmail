"""Tests for structured logging, trace_id propagation, and automatic redaction."""

from __future__ import annotations

import logging
from fastapi.testclient import TestClient

from mail_core.logging_config import (
    RedactingTraceFormatter,
    configure_logging,
    trace_scope,
)
from mail_core.security.redact import RedactingFilter


def test_configure_logging_reads_level_and_warns_on_invalid_value(monkeypatch, capsys):
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    try:
        monkeypatch.setenv("MAIL_CORE_LOG_LEVEL", "DEBUG")
        configure_logging(service_name="logging-level-test")
        assert root.level == logging.DEBUG
        logging.getLogger("logging-level-test").debug("debug level applied")

        monkeypatch.setenv("MAIL_CORE_LOG_LEVEL", "NOT_A_LEVEL")
        configure_logging(service_name="logging-level-test")
        assert root.level == logging.INFO
        logging.getLogger("logging-level-test").info("info fallback applied")

        output = capsys.readouterr().out
        assert "debug level applied" in output
        assert "invalid logging level 'NOT_A_LEVEL'; using INFO" in output
        assert "info fallback applied" in output
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            if handler not in original_handlers:
                handler.close()
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)


def test_redacting_trace_formatter_injects_trace_and_redacts():
    formatter = RedactingTraceFormatter("[%(trace_id)s] %(message)s")
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="connect postgresql://kkmail:my_super_secret@localhost:5432/db with token bearer ya29.secret_token",
        args=(),
        exc_info=None,
    )

    # When no trace_id is set
    out = formatter.format(record)
    assert "[-] " in out
    assert "my_super_secret" not in out
    assert "ya29.secret_token" not in out
    assert "[REDACTED]" in out

    # When trace_id is scoped
    with trace_scope("req_12345"):
        record2 = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=20,
            msg="job completed password='clear_text_pw'",
            args=(),
            exc_info=None,
        )
        out2 = formatter.format(record2)
        assert "[req_12345]" in out2
        assert "clear_text_pw" not in out2
        assert "[REDACTED]" in out2


def test_redacting_filter_sanitizes_record():
    rfilter = RedactingFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=15,
        msg="failed auth token %s with secret %s",
        args=("bearer ya29.testtoken", "client_secret: topsecret", "Basic dXNlcjpwYXNz", "http://user:secret123@proxy.corp:8080"),
        exc_info=None,
    )
    rfilter.filter(record)
    assert "ya29.testtoken" not in str(record.args)
    assert "topsecret" not in str(record.args)
    assert "dXNlcjpwYXNz" not in str(record.args)
    assert "secret123" not in str(record.args)
    assert "[REDACTED]" in str(record.args)


def test_http_request_id_middleware_and_trace_header():
    from mail_core.api.app import app

    client = TestClient(app)
    # Without incoming header
    resp = client.get("/health")
    assert resp.status_code == 200
    req_id = resp.headers.get("X-Request-ID")
    assert req_id is not None
    assert req_id.startswith("req_")

    # With incoming header
    custom_id = "custom-trace-999"
    resp2 = client.get("/health", headers={"X-Request-ID": custom_id})
    assert resp2.status_code == 200
    assert resp2.headers.get("X-Request-ID") == custom_id
