"""mail-core Cookie session + Bearer API key + CSRF."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mail_core.api.app import app
from mail_core.blobs.crypto import BlobCryptoError, load_keyring_from_env
from mail_core.security.auth import AuthConfigError, reset_auth_caches, validate_auth_config
from tests.mail_core.conftest import TEST_API_KEY, TEST_LOGIN_PASSWORD


@pytest.fixture(autouse=True)
def _reset_auth():
    reset_auth_caches()
    yield
    reset_auth_caches()


def test_unauthenticated_mail_returns_401():
    client = TestClient(app)
    res = client.get("/api/mail/inbox")
    assert res.status_code == 401


def test_health_public():
    assert TestClient(app).get("/health").status_code == 200


def test_api_key_ok(api_client):
    res = api_client.get("/api/mail/inbox")
    assert res.status_code != 401
    assert res.status_code != 403


def test_invalid_api_key_401():
    client = TestClient(app, headers={"Authorization": "Bearer wrong-key"})
    assert client.get("/api/mail/inbox").status_code == 401


def test_session_login_and_me():
    client = TestClient(app)
    bad = client.post("/api/auth/login", json={"password": "nope"})
    assert bad.status_code == 401

    ok = client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD})
    assert ok.status_code == 200
    csrf = ok.json()["csrf_token"]
    assert csrf
    assert "kkmail_mc_session" in ok.cookies

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["via"] == "session"
    assert me.json()["csrf_token"] == csrf

    inbox = client.get("/api/mail/inbox")
    assert inbox.status_code != 401


def test_csrf_rejection_on_mutating_session():
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD})
    csrf = login.json()["csrf_token"]

    missing = client.post(
        "/api/mail/messages/00000000-0000-0000-0000-000000000001/read",
        json={"is_read": True},
    )
    assert missing.status_code == 403
    assert missing.json()["detail"]["csrf_error"] is True

    wrong = client.post(
        "/api/mail/messages/00000000-0000-0000-0000-000000000001/read",
        json={"is_read": True},
        headers={"X-CSRF-Token": "not-the-token"},
    )
    assert wrong.status_code == 403

    bearer = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    r = bearer.post(
        "/api/mail/messages/00000000-0000-0000-0000-000000000001/read",
        json={"is_read": True},
    )
    assert r.status_code != 403

    good = client.post(
        "/api/mail/messages/00000000-0000-0000-0000-000000000001/read",
        json={"is_read": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert good.status_code != 403


def test_logout_clears_session():
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD})
    csrf = login.json()["csrf_token"]
    out = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_missing_blob_key_fails():
    with pytest.raises(BlobCryptoError, match="blob encryption keys required"):
        load_keyring_from_env(env={})


def test_auth_config_requires_secret(monkeypatch):
    monkeypatch.delenv("MAIL_CORE_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    reset_auth_caches()
    with pytest.raises(AuthConfigError, match="SECRET_KEY"):
        validate_auth_config()
