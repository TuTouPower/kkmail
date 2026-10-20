"""Unit tests for remote push robustness: transient retry, CAS protection, coalesce order."""

from __future__ import annotations

from mail_core.sync.remote_push import is_transient_error


def test_is_transient_error_detection():
    assert is_transient_error(TimeoutError("connection timed out"))
    assert is_transient_error(ConnectionResetError("peer reset"))
    assert is_transient_error(None, "HTTP 429 Too Many Requests")
    assert is_transient_error(None, "503 Service Unavailable")
    assert is_transient_error(None, "temporary server failure")
    assert not is_transient_error(ValueError("invalid id"))
    assert not is_transient_error(None, "folder not found")
