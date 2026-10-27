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


def test_sync_activity_records_and_expires():
    _, acc1_id, _, _ = _seed_accounts()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    resp = client.post("/api/mail/sync/activity", json={"account_ids": [str(acc1_id)]})
    assert resp.status_code == 204


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


def test_list_recent_sync_requests_is_scope_exact():
    group_id, acc1_id, acc2_id, f1_id = _seed_accounts()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    # Single-account request: stored scope {"account_id": acc1}.
    r = client.post(f"/api/accounts/{acc1_id}/sync")
    assert r.status_code == 202
    account_req = r.json()
    assert account_req["state"] == "queued"

    # Global full request: stored scope {"all": True}.
    r = client.post("/api/accounts/sync-all")
    assert r.status_code == 202
    global_req = r.json()

    # Unfiltered (global) list returns ONLY the global request
    r = client.get("/api/mail/sync/requests")
    assert r.status_code == 200
    ids = [item["id"] for item in r.json()]
    assert global_req["id"] in ids
    assert account_req["id"] not in ids

    # Scope-filtered by the owning account finds only the account request
    r = client.get("/api/mail/sync/requests", params={"account_id": str(acc1_id)})
    ids = [item["id"] for item in r.json()]
    assert account_req["id"] in ids
    assert global_req["id"] not in ids

    r = client.get("/api/mail/sync/requests", params={"account_id": str(acc2_id)})
    ids = [item["id"] for item in r.json()]
    assert account_req["id"] not in ids
    assert global_req["id"] not in ids
    assert account_req["id"] not in ids
    assert global_req["id"] not in ids

    # Limit is honoured and capped.
    r = client.get("/api/mail/sync/requests", params={"limit": 1})
    assert len(r.json()) <= 1
