"""Tests for adopted items (A2, A11, A25, A42, A44, A55)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from mail_core.api.app import app
from mail_core.providers.factory import is_private_host, validate_imap_host
from mail_core.realtime.dispatcher import OutboxDispatcher
from mail_core.security.auth import (
    cookie_secure,
    get_session_epoch,
    invalidate_all_sessions,
    reset_auth_caches,
)
from mail_core.threading.rules import assign_thread_for_message


def test_session_epoch_memory_cache_and_invalidation(monkeypatch):
    reset_auth_caches()
    query_count = 0

    class FakeSession:
        def get(self, model, pk):
            nonlocal query_count
            query_count += 1
            cred = MagicMock()
            cred.session_epoch = 42
            return cred

        def commit(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "postgresql://fake/db")
    monkeypatch.setattr("mail_core.db.session.get_session_factory", lambda: (lambda: FakeSession()))

    # First call queries DB
    assert get_session_epoch() == 42
    assert query_count == 1

    # Second call uses memory cache (no additional DB query)
    assert get_session_epoch() == 42
    assert query_count == 1

    # Invalidate cache resets the TTL; calling it queries once to bump in DB,
    # and subsequent get_session_epoch queries again because cache was invalidated.
    invalidate_all_sessions()
    assert query_count == 2
    assert get_session_epoch() == 42
    assert query_count == 3


def test_security_headers_middleware():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert "Strict-Transport-Security" in resp.headers


def test_cookie_secure_adaptive_forwarded_proto(monkeypatch):
    monkeypatch.delenv("MAIL_CORE_COOKIE_SECURE", raising=False)

    req_http = MagicMock()
    req_http.headers = {"x-forwarded-proto": "http"}
    req_http.url.scheme = "http"
    assert cookie_secure(req_http) is False

    req_https = MagicMock()
    req_https.headers = {"x-forwarded-proto": "https"}
    req_https.url.scheme = "http"
    assert cookie_secure(req_https) is True

    # Explicit env override takes precedence
    monkeypatch.setenv("MAIL_CORE_COOKIE_SECURE", "0")
    assert cookie_secure(req_https) is False


def test_ssrf_imap_host_validation(monkeypatch):
    monkeypatch.delenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", raising=False)

    assert is_private_host("127.0.0.1") is True
    assert is_private_host("10.0.0.1") is True
    assert is_private_host("192.168.1.1") is True
    assert is_private_host("localhost") is True

    with pytest.raises(ValueError, match="SSRF protection"):
        validate_imap_host("127.0.0.1")

    with pytest.raises(ValueError, match="SSRF protection"):
        validate_imap_host("10.20.30.40")

    # Allowed when env set
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")
    validate_imap_host("127.0.0.1")  # does not raise


def test_threading_savepoint_conflict_retry():
    session = MagicMock()
    existing_thread = MagicMock()
    existing_thread.id = uuid4()
    existing_thread.sort_time = None
    existing_thread.provider_thread_key = "key1"

    nested_call_count = 0

    class FakeSavepoint:
        def __enter__(self):
            nonlocal nested_call_count
            nested_call_count += 1
            if nested_call_count == 1:
                # First attempt raises IntegrityError
                raise IntegrityError("duplicate key", params=None, orig=Exception())
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            return False

    session.begin_nested = FakeSavepoint
    session.scalar.return_value = existing_thread

    msg = MagicMock()
    msg.account_id = uuid4()
    msg.internet_message_id = None
    msg.subject = "Test"
    msg.sort_time = None
    msg.thread_id = None

    assignment = assign_thread_for_message(
        session,
        message=msg,
        provider_thread_key="key1",
    )
    assert assignment.thread_id == existing_thread.id


def test_dispatcher_fanout_empty_targets_returns_false():
    dispatcher = OutboxDispatcher()
    # No subscribers registered -> targets will be empty
    assert dispatcher._fanout({"id": 1, "account_id": None, "event": "test"}) is False
