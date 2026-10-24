"""Unit tests for remote push robustness: transient retry, CAS protection, coalesce order."""

from __future__ import annotations

from mail_core.providers.http import ProviderHttpError, RateLimitedError
from mail_core.sync.remote_push import is_rate_limited_error, is_transient_error


def test_is_transient_error_detection():
    assert is_transient_error(TimeoutError("connection timed out"))
    assert is_transient_error(ConnectionResetError("peer reset"))
    assert is_transient_error(None, "HTTP 429 Too Many Requests")
    assert is_transient_error(None, "HTTPError 500 Server Error")
    assert is_transient_error(None, "503 Service Unavailable")
    assert is_transient_error(None, "Service Unavailable")
    assert is_transient_error(None, "temporary server failure")
    assert is_transient_error(None, "TimeoutError")
    assert is_transient_error(None, "Connection reset by peer")
    assert is_transient_error(None, "ProviderHttpError status=503")
    assert is_transient_error(ProviderHttpError("unavailable", status=503))
    assert not is_transient_error(ValueError("invalid id"))
    assert not is_transient_error(None, "folder not found")
    assert not is_transient_error(None, "provider reported: Service Unavailable")
    assert not is_transient_error(None, "mail id 429 is not a status")
    assert not is_transient_error(None, "batch 429 contained 500 messages")
    assert not is_transient_error(None, "500 messages processed")
    assert not is_transient_error(
        ProviderHttpError("HTTP 500 Internal Server Error", status=400),
        "HTTP 500 Internal Server Error",
    )


def test_is_rate_limited_error_requires_status_or_known_prefix():
    assert is_rate_limited_error(RateLimitedError("rate limited"))
    assert is_rate_limited_error(None, "HTTP 429 Too Many Requests")
    assert is_rate_limited_error(None, "RateLimitedError")
    assert is_rate_limited_error(None, "rate limit exceeded")
    assert not is_rate_limited_error(None, "mail id 429 is not a status")
    assert not is_rate_limited_error(
        ProviderHttpError("bad request", status=400),
        "HTTP 429 Too Many Requests",
    )
