"""A105: a successful password change must end the current session explicitly.

change_login_password invalidates every session (epoch bump), including the
caller's own cookie, but the /api/auth/password response used to return a
bare ok with the now-dead cookie still set, leaving clients in a confusing
half-logged-in state. The response must clear the session cookie and state
that a fresh login is required.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mail_core.api.app import app
from mail_core.security.auth import reset_auth_caches
from tests.mail_core.conftest import TEST_LOGIN_PASSWORD


@pytest.fixture(autouse=True)
def _reset_auth():
    reset_auth_caches()
    yield
    reset_auth_caches()


def test_password_change_clears_session_cookie_and_requires_relogin():
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]

    ch = client.post(
        "/api/auth/password",
        json={
            "current_login_password": TEST_LOGIN_PASSWORD,
            "login_password": "new_secret_password_105",
        },
        headers={"X-CSRF-Token": csrf},
    )
    assert ch.status_code == 200
    body = ch.json()
    assert body["requires_relogin"] is True

    set_cookie = "; ".join(ch.headers.get_list("set-cookie"))
    assert "kkmail_mc_session=" in set_cookie
    # The cleared cookie carries no session value.
    assert "kkmail_mc_session=;" in set_cookie or 'kkmail_mc_session=""' in set_cookie or "kkmail_mc_session= " in set_cookie

    # The session really is over: the client is unauthenticated now.
    assert client.get("/api/auth/me").status_code == 401
