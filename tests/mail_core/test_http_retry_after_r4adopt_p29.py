"""A292: ``Retry-After`` may be an HTTP-date (RFC 9110 allows
delay-seconds or HTTP-date); the date form used to be silently discarded
because only ``float()`` was tried, so throttled callers lost their
backoff hint.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from mail_core.providers.http import RateLimitedError


def test_retry_after_http_date_is_converted_to_remaining_seconds():
    future = datetime.now(timezone.utc) + timedelta(seconds=120)
    err = RateLimitedError(headers={"Retry-After": format_datetime(future)})
    assert err.retry_after_seconds is not None
    assert 100 < err.retry_after_seconds <= 120


def test_retry_after_past_http_date_clamps_to_zero():
    past = datetime.now(timezone.utc) - timedelta(seconds=30)
    err = RateLimitedError(headers={"Retry-After": format_datetime(past)})
    assert err.retry_after_seconds == 0.0


def test_retry_after_delay_seconds_still_supported():
    err = RateLimitedError(headers={"Retry-After": "45"})
    assert err.retry_after_seconds == 45.0


def test_retry_after_unparseable_stays_none():
    err = RateLimitedError(headers={"Retry-After": "whenever"})
    assert err.retry_after_seconds is None


def test_retry_after_explicit_value_wins_over_header():
    err = RateLimitedError(retry_after_seconds=7, headers={"Retry-After": "45"})
    assert err.retry_after_seconds == 7.0


