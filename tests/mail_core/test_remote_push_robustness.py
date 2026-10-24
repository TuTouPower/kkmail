"""Unit tests for remote push robustness: transient retry, CAS protection, coalesce order."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.providers.http import ProviderHttpError, RateLimitedError
from mail_core.sync.remote_push import (
    get_unconverged_field_intents,
    is_rate_limited_error,
    is_transient_error,
)


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


def test_latest_created_field_intent_wins_over_stale_done_intent():
    created_at = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)
    stale_done = SimpleNamespace(
        id=uuid.UUID(int=1),
        entity_key="msg:remote-1:read",
        desired_state={"is_read": True},
        status=RemoteOperationStatus.DONE.value,
        created_at=created_at,
        updated_at=created_at + timedelta(seconds=1),
    )
    newer_pending = SimpleNamespace(
        id=uuid.UUID(int=2),
        entity_key="msg:remote-1:read",
        desired_state={"is_read": False},
        status=RemoteOperationStatus.PENDING.value,
        created_at=created_at + timedelta(seconds=2),
        updated_at=created_at + timedelta(seconds=2),
    )

    class Result:
        def all(self):
            return sorted(
                [newer_pending, stale_done],
                key=lambda op: (op.created_at, op.id),
            )

    class Session:
        statement = None

        def scalars(self, statement):
            self.statement = statement
            return Result()

    session = Session()
    intents = get_unconverged_field_intents(
        session,
        uuid.uuid4(),
        ["remote-1"],
        now=created_at + timedelta(seconds=3),
    )

    sql = str(session.statement).lower()
    order_by = sql.split("order by", 1)[1]
    assert "remote_operations.created_at asc" in order_by
    assert "remote_operations.id asc" in order_by
    assert intents == {"remote-1": {"is_read": False}}


def test_field_intents_preserve_colons_in_remote_ids():
    created_at = datetime(2026, 10, 25, 10, 0, tzinfo=timezone.utc)
    operations = [
        SimpleNamespace(
            entity_key="msg:remote:with:colon:read",
            desired_state={"is_read": False},
        ),
        SimpleNamespace(
            entity_key="msg:remote:with:colon:flag",
            desired_state={"is_flagged": True},
        ),
    ]

    class Result:
        def all(self):
            return operations

    class Session:
        def scalars(self, _statement):
            return Result()

    intents = get_unconverged_field_intents(
        Session(),
        uuid.uuid4(),
        ["remote:with:colon"],
        now=created_at,
    )

    assert intents == {"remote:with:colon": {"is_read": False, "is_flagged": True}}
