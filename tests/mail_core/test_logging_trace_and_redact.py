"""Tests for structured logging, trace_id propagation, and automatic redaction."""

from __future__ import annotations

import logging
import sys
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


def test_redacting_trace_formatter_preserves_long_traceback_tail():
    formatter = RedactingTraceFormatter("%(message)s")
    try:
        raise RuntimeError("final-root-cause password=clear_text_pw")
    except RuntimeError:
        exc_info = sys.exc_info()

    record = logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=10,
        msg="context " + ("x" * 5000),
        args=(),
        exc_info=exc_info,
    )

    out = formatter.format(record)

    assert len(out) > 4000
    assert "RuntimeError: final-root-cause password=[REDACTED]" in out
    assert "clear_text_pw" not in out


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

    # Valid incoming ids are echoed; malformed and overlong values are replaced.
    custom_id = "custom-trace-999"
    resp2 = client.get("/health", headers={"X-Request-ID": custom_id})
    assert resp2.status_code == 200
    assert resp2.headers.get("X-Request-ID") == custom_id

    for header, invalid_id in (
        ("X-Request-ID", "bad request id"),
        ("X-Request-ID", "x" * 65),
        ("X-Trace-ID", "x" * 65),
    ):
        response = client.get("/health", headers={header: invalid_id})
        generated_id = response.headers["X-Request-ID"]
        assert response.status_code == 200
        assert generated_id.startswith("req_")
        assert len(generated_id) <= 64
        assert generated_id != invalid_id

    trace_id = "trace.v1-_09"
    response = client.get("/health", headers={"X-Trace-ID": trace_id})
    assert response.headers["X-Request-ID"] == trace_id


def test_redact_handles_token_keys_and_query_params():
    from mail_core.security.redact import redact

    text1 = "auth failure token=SECRET_RAW_TOKEN_999 and token: 'SECRET_QUOTED_888'"
    redacted1 = redact(text1)
    assert "SECRET_RAW_TOKEN" not in redacted1
    assert "SECRET_QUOTED" not in redacted1
    assert "[REDACTED]" in redacted1

    text2 = 'JSON payload: {"token": "SECRET_JSON_777", "other": "ok"}'
    redacted2 = redact(text2)
    assert "SECRET_JSON" not in redacted2
    assert "[REDACTED]" in redacted2

    text3 = "GET https://api.provider.com/v1/sync?token=QUERY_TOKEN_555&next_cursor=xyz"
    redacted3 = redact(text3)
    assert "QUERY_TOKEN" not in redacted3
    assert "xyz" in redacted3


def test_redacting_trace_formatter_provider_exception_chain_never_leaks_body_or_token():
    import io
    from mail_core.providers.http import ProviderHttpError

    logger = logging.getLogger("test_provider_leak_prevention")
    logger.setLevel(logging.DEBUG)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    formatter = RedactingTraceFormatter("[%(trace_id)s] %(levelname)s %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    try:
        try:
            raise ProviderHttpError(
                "Sensitive crash message token=SECRET_LEAK_111",
                status=500,
                body={"raw_body_secret": "TOP_SECRET_BODY_PAYLOAD_222"},
            )
        except Exception as exc:
            try:
                raise RuntimeError("Outer operation failed: token=SECRET_LEAK_333") from exc
            except Exception:
                with trace_scope("trace_provider_leak_test"):
                    logger.exception("Provider call encountered critical failure")

        log_output = stream.getvalue()
        assert "[trace_provider_leak_test]" in log_output
        assert "SECRET_LEAK_111" not in log_output
        assert "TOP_SECRET_BODY_PAYLOAD_222" not in log_output
        assert "SECRET_LEAK_333" not in log_output
        assert "ProviderHttpError status=500" in log_output
        assert "RuntimeError" in log_output
    finally:
        logger.removeHandler(handler)
