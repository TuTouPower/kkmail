"""Accounts / groups / settings routes against Postgres (typed contracts)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import Account, Attachment, Message
from tests.mail_core.conftest import TEST_API_KEY

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

# These PG fixtures create accounts through the API with the "memory" test
# provider, which the production API rejects unless test fixtures opt in
# via the environment switch (A103).
os.environ.setdefault("MAIL_CORE_ALLOW_TEST_PROVIDERS", "1")


def _client() -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})


def test_group_and_account_lifecycle():
    c = _client()
    g = c.post("/api/groups", json={"name": f"g-{uuid.uuid4().hex[:6]}"})
    assert g.status_code == 200
    gid = g.json()["id"]
    groups = c.get("/api/groups").json()["groups"]
    assert any(x["id"] == gid for x in groups)

    email = f"acct-{uuid.uuid4().hex[:8]}@example.com"
    a = c.post("/api/accounts", json={"email": email, "provider": "memory", "group_id": gid})
    assert a.status_code == 200, a.text
    aid = a.json()["id"]
    page = c.get("/api/accounts", params={"limit": 500}).json()
    assert set(page) == {"accounts", "total", "limit", "offset", "has_more"}
    assert any(x["id"] == aid and x["group_id"] == gid for x in page["accounts"])

    sync = c.post(f"/api/accounts/{aid}/sync")
    assert sync.status_code == 202 and uuid.UUID(sync.json()["id"])
    all_ = c.post("/api/accounts/sync-all")
    assert all_.status_code == 202 and uuid.UUID(all_.json()["id"])

    assert c.delete(f"/api/accounts/{aid}").status_code == 204
    assert c.delete(f"/api/accounts/{aid}").status_code == 404
    assert c.delete(f"/api/groups/{gid}").status_code == 204


def test_settings_rejects_unknown_and_secret_keys():
    c = _client()
    ok = c.put("/api/settings", json={"settings": {"app_timezone": "Asia/Shanghai"}})
    assert ok.status_code == 200
    assert ok.json()["settings"]["app_timezone"] == "Asia/Shanghai"
    assert c.put("/api/settings", json={"settings": {"login_password": "x"}}).status_code == 400
    assert c.put("/api/settings", json={"settings": {"nope": "1"}}).status_code == 400
    # POST alias removed: one verb per operation.
    assert c.post("/api/settings", json={"settings": {}}).status_code == 405


def test_group_rename_validation_and_nonempty_delete_preserve_mail_data():
    c = _client()
    group = c.post("/api/groups", json={"name": f"rename-{uuid.uuid4().hex}"})
    assert group.status_code == 200, group.text
    group_id = group.json()["id"]
    duplicate = c.post("/api/groups", json={"name": f"duplicate-{uuid.uuid4().hex}"})
    assert duplicate.status_code == 200, duplicate.text
    duplicate_id = duplicate.json()["id"]
    duplicate_name = duplicate.json()["name"]

    normalized_name = "x" * 128
    renamed = c.patch(f"/api/groups/{group_id}", json={"name": f" {normalized_name} "})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == normalized_name
    assert c.patch(f"/api/groups/{group_id}", json={"name": f"{normalized_name}x"}).status_code == 422
    assert c.patch(f"/api/groups/{group_id}", json={"name": "   "}).status_code == 422
    assert c.patch(f"/api/groups/{group_id}", json={"name": duplicate_name}).status_code == 400
    assert c.patch(f"/api/groups/{uuid.uuid4()}", json={"name": "missing"}).status_code == 404
    groups_after_failure = c.get("/api/groups").json()["groups"]
    assert any(item["id"] == group_id and item["name"] == normalized_name for item in groups_after_failure)

    email = f"preserve-{uuid.uuid4().hex}@example.test"
    account_response = c.post("/api/accounts", json={"email": email, "provider": "memory", "group_id": group_id})
    assert account_response.status_code == 200, account_response.text
    account_id = uuid.UUID(account_response.json()["id"])
    Session = get_session_factory()
    timestamp = datetime.now(timezone.utc)
    with Session() as session:
        account = session.get(Account, account_id)
        assert account is not None
        account.credential_ref = f"env:preserve-{uuid.uuid4().hex}"
        account.master_order = 7
        account.group_order = 2
        message = Message(
            account_id=account_id,
            remote_id=f"preserve-{uuid.uuid4().hex}",
            subject="Keep with group deletion",
            from_address="sender@example.test",
            sort_time=timestamp,
            has_attachments=True,
        )
        session.add(message)
        session.flush()
        attachment = Attachment(message_id=message.id, filename="retained.txt", content_type="text/plain", size_bytes=8)
        session.add(attachment)
        session.commit()
        message_id, attachment_id = message.id, attachment.id

    deleted = c.delete(f"/api/groups/{group_id}")
    assert deleted.status_code == 204
    with Session() as session:
        account = session.get(Account, account_id)
        message = session.get(Message, message_id)
        attachment = session.get(Attachment, attachment_id)
        assert account is not None and account.group_id is None and account.master_order == 7
        assert account.credential_ref.startswith("env:preserve-")
        assert account.group_order is None
        assert message is not None and message.account_id == account_id
        assert attachment is not None and attachment.message_id == message_id
