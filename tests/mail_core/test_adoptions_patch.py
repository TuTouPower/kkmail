"""Tests for adopted items (A2, A11, A25, A42, A44, A55)."""

from __future__ import annotations

import socket
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


# Note on deleted tests:
# - test_session_epoch_memory_cache_and_invalidation: Removed per A37 decision, then
#   superseded by A86's bounded 5s cache; cache expiry and local invalidation are tested
#   in test_auth_plan_a_db.py.
# - test_cookie_secure_adaptive_forwarded_proto: Removed per A21 decision.
#   Direct trust of raw X-Forwarded-Proto headers was removed to prevent forged header bypass.
#   cookie_secure now only trusts explicit config or verified ASGI scheme. Replaced by test_cookie_secure_boundary in test_auth.py.


def test_security_headers_middleware():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    # A284 semantic change: HSTS is only sent on HTTPS requests, so the
    # plain-HTTP default TestClient must not see it; the HTTPS client must.
    assert "Strict-Transport-Security" not in resp.headers
    https_resp = TestClient(app, base_url="https://testserver").get("/health")
    assert "Strict-Transport-Security" in https_resp.headers


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


def test_ssrf_rejects_dns_answers_mixing_public_and_private_ips(monkeypatch):
    monkeypatch.delenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", raising=False)
    monkeypatch.setattr(
        "mail_core.providers.factory.socket.getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 993)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.8", 993)),
        ],
    )

    with pytest.raises(ValueError, match="SSRF protection"):
        validate_imap_host("mail.example.test")


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
