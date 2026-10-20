"""Account API auth gate (no DB required for 401)."""

from fastapi.testclient import TestClient

from mail_core.api.app import app


def test_accounts_require_auth():
    client = TestClient(app)
    assert client.get("/api/accounts").status_code == 401
    assert client.get("/api/groups").status_code == 401
    assert client.get("/api/settings").status_code == 401


def test_account_create_validation_constraints(api_client):
    # Invalid provider
    res = api_client.post("/api/accounts", json={"email": "a@ex.com", "provider": "invalid_provider"})
    assert res.status_code == 422

    # display_name too long (> 255)
    res = api_client.post(
        "/api/accounts",
        json={"email": "a@ex.com", "provider": "imap", "display_name": "x" * 256},
    )
    assert res.status_code == 422


def test_account_update_validation_constraints(api_client):
    # display_name too long (> 255)
    res = api_client.patch(
        "/api/accounts/00000000-0000-0000-0000-000000000001",
        json={"display_name": "x" * 256},
    )
    assert res.status_code == 422


def test_group_create_validation_constraints(api_client):
    # color too long (> 32)
    res = api_client.post("/api/groups", json={"name": "Work", "color": "c" * 33})
    assert res.status_code == 422

