"""Unit-mode coverage for Package A sync-request entry fixes (R02/R09/R10 + p053).

These tests deliberately avoid PostgreSQL: the DeltaSyncIn default factory,
client_request_id length validation, scope canonicalization used by the
idempotency check, and the Cookie-session CSRF rejection (which happens in
the auth dependency, before any database access) all run without a DB.
PostgreSQL-backed success/dedupe paths live in test_sync_requests.py.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from mail_core.api.app import app
from mail_core.api.mail import DeltaSyncIn
from mail_core.mail.application.sync_requests import _canonical_scope, _intent_matches
from mail_core.mail.storage.models import SyncRequest
from tests.mail_core.conftest import TEST_LOGIN_PASSWORD


def test_delta_sync_in_omitted_client_request_id_gets_server_default():
    """R10: omitting client_request_id must construct (uuid default factory)."""
    first = DeltaSyncIn()
    second = DeltaSyncIn()
    assert first.client_request_id
    assert len(first.client_request_id) <= 64
    assert first.client_request_id != second.client_request_id
    assert first.folder_role == "inbox"
    assert first.trigger == "manual"


def test_delta_sync_in_rejects_out_of_range_client_request_id():
    """R02/3.2: client_request_id input is bounded to the VARCHAR(64) column."""
    with pytest.raises(ValidationError):
        DeltaSyncIn(client_request_id="x" * 65)
    with pytest.raises(ValidationError):
        DeltaSyncIn(client_request_id="")
    assert DeltaSyncIn(client_request_id="x" * 64).client_request_id == "x" * 64


def test_canonical_scope_normalizes_uuid_spelling_and_ignores_non_scope_keys():
    account_id = uuid.uuid4()
    from_dict = _canonical_scope(
        {"account_id": account_id, "folder_role": "sent", "trigger": "manual", "client_request_id": "abc"}
    )
    from_args = _canonical_scope({}, account_id=account_id, folder_role="sent")
    assert from_dict == from_args == {"account_id": str(account_id), "folder_role": "sent"}


def test_intent_matches_only_for_same_mode_trigger_and_scope():
    account_id = uuid.uuid4()
    existing = SyncRequest(
        id=uuid.uuid4(),
        client_request_id="req-1",
        mode="delta",
        trigger="manual",
        state="queued",
        # Legacy stored scope: a raw request dump including non-scope keys.
        scope={"account_id": str(account_id), "folder_role": "inbox", "trigger": "manual", "client_request_id": "req-1"},
    )
    canonical = _canonical_scope({}, account_id=account_id, folder_role="inbox")
    assert _intent_matches(existing, mode="delta", trigger="manual", canonical_scope=canonical)
    assert not _intent_matches(existing, mode="full", trigger="manual", canonical_scope=canonical)
    assert not _intent_matches(existing, mode="delta", trigger="focus", canonical_scope=canonical)
    other = _canonical_scope({}, account_id=account_id, folder_role="sent")
    assert not _intent_matches(existing, mode="delta", trigger="manual", canonical_scope=other)


def test_sync_delta_cookie_session_requires_csrf_token():
    """p053: Cookie-session POST /api/mail/sync/delta without a valid
    X-CSRF-Token is rejected with the structured CSRF error, before any
    database work. (Bearer API-key auth is CSRF-exempt and does not cover
    this path, which is why the existing suite missed it.)"""
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    assert csrf

    body = {"client_request_id": f"csrf-unit-{uuid.uuid4().hex}"}

    missing = client.post("/api/mail/sync/delta", json=body)
    assert missing.status_code == 403
    assert missing.json()["detail"]["csrf_error"] is True

    wrong = client.post("/api/mail/sync/delta", json=body, headers={"X-CSRF-Token": "not-the-token"})
    assert wrong.status_code == 403
    assert wrong.json()["detail"]["csrf_error"] is True
