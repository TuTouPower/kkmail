"""Tests for scoped delta/full synchronization requests and activity tracking (D10)."""

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import Account, AccountGroup, Folder, SyncRequest
from mail_core.mail.application.sync_requests import (
    create_sync_request,
    get_sync_request_report,
    record_account_activity,
)
from tests.mail_core.conftest import TEST_API_KEY

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_accounts():
    Session = get_session_factory()
    with Session() as session:
        group = AccountGroup(name="Finance Group", sort_order=0)
        session.add(group)
        session.flush()

        acc1 = Account(
            email=f"acc1-{uuid.uuid4().hex[:6]}@example.com",
            provider="imap",
            group_id=group.id,
            sync_enabled=True,
        )
        acc2 = Account(
            email=f"acc2-{uuid.uuid4().hex[:6]}@example.com",
            provider="imap",
            sync_enabled=False,  # Disabled account
        )
        session.add_all([acc1, acc2])
        session.flush()

        f1 = Folder(account_id=acc1.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(f1)
        session.commit()
        return group.id, acc1.id, acc2.id, f1.id


def test_create_delta_request_idempotency_by_client_request_id():
    group_id, acc1_id, acc2_id, f1_id = _seed_accounts()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    client_req_id = f"test-client-req-{uuid.uuid4().hex}"
    body = {
        "account_id": str(acc1_id),
        "trigger": "manual",
        "client_request_id": client_req_id,
    }

    # 1. First POST
    r1 = client.post("/api/mail/sync/delta", json=body)
    assert r1.status_code == 202
    data1 = r1.json()
    assert data1["mode"] == "delta"
    assert data1["target_count"] >= 1
    assert data1["state"] == "queued"

    # 2. Duplicate POST with same client_request_id -> returns same request
    r2 = client.post("/api/mail/sync/delta", json=body)
    assert r2.status_code == 202
    data2 = r2.json()
    assert data2["id"] == data1["id"]

    # 3. GET /sync/requests/{id}
    r3 = client.get(f"/api/mail/sync/requests/{data1['id']}")
    assert r3.status_code == 200
    assert r3.json()["id"] == data1["id"]


def test_sync_request_disabled_account_raises_409():
    _, _, acc2_id, _ = _seed_accounts()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    body = {
        "account_id": str(acc2_id),
        "trigger": "manual",
        "client_request_id": f"disabled-test-{uuid.uuid4().hex}",
    }
    resp = client.post("/api/mail/sync/delta", json=body)
    assert resp.status_code == 409
    assert "account_disabled" in resp.text


def test_sync_activity_records_and_expires():
    _, acc1_id, _, _ = _seed_accounts()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    resp = client.post("/api/mail/sync/activity", json={"account_ids": [str(acc1_id)]})
    assert resp.status_code == 204


def test_sync_delta_cookie_session_csrf_enforced_and_valid_token_accepted():
    """p053: the Cookie-session path (what browsers/Electron actually use)
    must enforce CSRF on /sync/delta — Bearer-only coverage cannot see this."""
    from tests.mail_core.conftest import TEST_LOGIN_PASSWORD

    _, acc1_id, _, _ = _seed_accounts()
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]

    body = {
        "account_id": str(acc1_id),
        "trigger": "manual",
        "client_request_id": f"cookie-csrf-{uuid.uuid4().hex}",
    }

    missing = client.post("/api/mail/sync/delta", json=body)
    assert missing.status_code == 403
    assert missing.json()["detail"]["csrf_error"] is True

    wrong = client.post("/api/mail/sync/delta", json=body, headers={"X-CSRF-Token": "not-the-token"})
    assert wrong.status_code == 403
    assert wrong.json()["detail"]["csrf_error"] is True

    ok = client.post("/api/mail/sync/delta", json=body, headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 202
    assert ok.json()["mode"] == "delta"


def test_sync_delta_same_id_different_intent_conflicts_409():
    """R02/3.2 dedupe: same client_request_id + different intent is a 409,
    while the same ID + same intent keeps returning the original request."""
    _, acc1_id, _, f1_id = _seed_accounts()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    client_req_id = f"dedupe-{uuid.uuid4().hex}"

    base = {"account_id": str(acc1_id), "trigger": "manual", "client_request_id": client_req_id}
    first = client.post("/api/mail/sync/delta", json=base)
    assert first.status_code == 202

    same = client.post("/api/mail/sync/delta", json=base)
    assert same.status_code == 202
    assert same.json()["id"] == first.json()["id"]

    different_scope = client.post(
        "/api/mail/sync/delta", json={**base, "folder_id": str(f1_id)}
    )
    assert different_scope.status_code == 409

    different_trigger = client.post("/api/mail/sync/delta", json={**base, "trigger": "focus"})
    assert different_trigger.status_code == 409


def test_single_account_full_sync_succeeds_with_generated_id_within_column_limit():
    """R02: POST /api/accounts/{id}/sync previously generated a 74-char
    client_request_id for a VARCHAR(64) column and always failed with 500."""
    _, acc1_id, _, _ = _seed_accounts()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    resp = client.post(f"/api/accounts/{acc1_id}/sync")
    assert resp.status_code == 202, resp.text
    data = resp.json()
    assert data["mode"] == "full"
    assert data["target_count"] >= 1

    Session = get_session_factory()
    with Session() as session:
        stored = session.get(SyncRequest, uuid.UUID(data["id"]))
        assert stored is not None
        assert len(stored.client_request_id) <= 64
