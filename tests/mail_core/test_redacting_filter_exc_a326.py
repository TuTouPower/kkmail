"""A326: RedactingFilter alone (plain Formatter) must not leak tracebacks."""

from __future__ import annotations

import logging
import sys

from mail_core.security.redact import RedactingFilter


def _record_with_exc() -> logging.LogRecord:
    try:
        raise RuntimeError("boom password=filter_secret_pw token=abc123token")
    except RuntimeError:
        exc_info = sys.exc_info()
    return logging.LogRecord(
        name="test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="operation failed",
        args=(),
        exc_info=exc_info,
    )


def test_filter_redacts_exc_info_for_plain_formatter():
    record = _record_with_exc()
    assert RedactingFilter().filter(record) is True

    out = logging.Formatter("%(message)s").format(record)
    assert "RuntimeError" in out
    assert "filter_secret_pw" not in out
    assert "abc123token" not in out
    assert "[REDACTED]" in out


def test_filter_redacts_prebuilt_exc_text():
    record = _record_with_exc()
    record.exc_info = None
    record.exc_text = "Traceback (fake): ValueError: token=prebuilt_secret_777"

    assert RedactingFilter().filter(record) is True
    out = logging.Formatter("%(message)s").format(record)
    assert "prebuilt_secret_777" not in out
    assert "[REDACTED]" in out


def test_filter_without_exception_is_unchanged():
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="plain message",
        args=(),
        exc_info=None,
    )
    assert RedactingFilter().filter(record) is True
    assert record.exc_text is None
    assert logging.Formatter("%(message)s").format(record) == "plain message"
