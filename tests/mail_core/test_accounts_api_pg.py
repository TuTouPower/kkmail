"""Accounts / groups / settings routes against Postgres (typed contracts)."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from mail_core.api.app import app
from tests.mail_core.conftest import TEST_API_KEY

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


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
    assert sync.status_code == 200 and uuid.UUID(sync.json()["job_id"])
    all_ = c.post("/api/accounts/sync-all").json()
    assert all_["count"] == len(all_["job_ids"]) >= 1

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
