"""mail-core Cookie session + Bearer API key + CSRF."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from fastapi.security import HTTPAuthorizationCredentials
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


DATABASE_URL = os.environ.get("MAIL_CORE_DATABASE_URL")


def test_health_public():
    assert TestClient(app).get("/health").status_code == 200


@pytest.mark.skipif(not DATABASE_URL, reason="database required")
def test_api_key_ok(api_client):
    res = api_client.get("/api/mail/inbox")
    assert res.status_code != 401
    assert res.status_code != 403


def test_invalid_api_key_401():
    client = TestClient(app, headers={"Authorization": "Bearer wrong-key"})
    assert client.get("/api/mail/inbox").status_code == 401


def test_authenticated_api_keys_have_distinct_oauth_flow_bindings(monkeypatch):
    import mail_core.api.deps as auth_deps
    from mail_core.accounts.oauth_flow import session_binding_key
    from mail_core.security.auth import AuthPrincipal, digest_api_key

    monkeypatch.setattr(auth_deps, "api_key_matches", lambda _token: True)
    request = SimpleNamespace(headers={})

    def authenticate(key):
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=key)
        return auth_deps.authenticate_request(request, bearer_creds=credentials, cookie_token=None)

    first_key = "api-key-first-for-test"
    second_key = "api-key-second-for-test"
    first = authenticate(first_key)
    second = authenticate(second_key)

    assert first.api_key_digest == digest_api_key(first_key)
    assert session_binding_key(first) != session_binding_key(second)
    assert first_key not in session_binding_key(first)
    with pytest.raises(PermissionError, match="authentication required"):
        session_binding_key(AuthPrincipal(via="api_key"))


@pytest.mark.skipif(not DATABASE_URL, reason="database required")
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


@pytest.mark.skipif(not DATABASE_URL, reason="database required")
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
    old_cookie = client.cookies.get("kkmail_mc_session")
    out = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 200
    assert client.get("/api/auth/me").status_code == 401

    stale_client = TestClient(app, cookies={"kkmail_mc_session": old_cookie})
    assert stale_client.get("/api/auth/me").status_code == 401


def test_password_change_invalidates_session():
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD})
    csrf = login.json()["csrf_token"]
    old_cookie = client.cookies.get("kkmail_mc_session")

    ch = client.post(
        "/api/auth/password",
        json={"current_login_password": TEST_LOGIN_PASSWORD, "login_password": "new_secret_password_123"},
        headers={"X-CSRF-Token": csrf},
    )
    assert ch.status_code == 200

    stale_client = TestClient(app, cookies={"kkmail_mc_session": old_cookie})
    assert stale_client.get("/api/auth/me").status_code == 401


def test_missing_blob_key_fails():
    with pytest.raises(BlobCryptoError, match="blob encryption keys required"):
        load_keyring_from_env(env={})


def test_auth_config_requires_secret(monkeypatch):
    monkeypatch.delenv("MAIL_CORE_SECRET_KEY", raising=False)
    reset_auth_caches()
    with pytest.raises(AuthConfigError, match="MAIL_CORE_SECRET_KEY"):
        validate_auth_config()


def test_login_rate_limited_per_client():
    from mail_core.security.ratelimit import login_limiter

    login_limiter.reset()
    client = TestClient(app)
    try:
        for _ in range(login_limiter.max_failures):
            assert client.post("/api/auth/login", json={"password": "wrong"}).status_code == 401
        blocked = client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD})
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1
    finally:
        login_limiter.reset()
    assert client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD}).status_code == 200


def test_limiter_window_expires():
    from mail_core.security.ratelimit import LoginRateLimiter

    lim = LoginRateLimiter(max_failures=2, window_s=10)
    lim.record_failure("a", now=0)
    lim.record_failure("a", now=1)
    assert lim.retry_after("a", now=2) > 0
    assert lim.retry_after("b", now=2) == 0
    assert lim.retry_after("a", now=12) == 0


def test_login_rate_limiter_not_bypassed_by_forged_x_forwarded_for():
    """A21: Untrusted client cannot bypass login rate limit by forging X-Forwarded-For."""
    from mail_core.security.ratelimit import login_limiter

    login_limiter.reset()
    client = TestClient(app)
    try:
        # Attacker rotates X-Forwarded-For on each attempt
        for i in range(login_limiter.max_failures):
            res = client.post(
                "/api/auth/login",
                json={"password": "wrong"},
                headers={"X-Forwarded-For": f"198.51.100.{i + 1}"},
            )
            assert res.status_code == 401

        # Even with a brand new forged IP, request is blocked by real socket peer
        blocked = client.post(
            "/api/auth/login",
            json={"password": TEST_LOGIN_PASSWORD},
            headers={"X-Forwarded-For": "203.0.113.99"},
        )
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1
    finally:
        login_limiter.reset()


def test_cookie_secure_boundary(monkeypatch):
    """A21: cookie_secure only uses explicit config or verified ASGI scheme, never unvalidated headers."""
    from starlette.requests import Request
    from mail_core.security.auth import cookie_secure

    monkeypatch.delenv("MAIL_CORE_COOKIE_SECURE", raising=False)

    # 1. Plain HTTP request with unvalidated X-Forwarded-Proto: https -> must be False
    plain_scope = {
        "type": "http",
        "scheme": "http",
        "path": "/",
        "headers": [(b"x-forwarded-proto", b"https"), (b"host", b"localhost:8000")],
        "server": ("127.0.0.1", 8000),
    }
    req_plain = Request(plain_scope)
    assert not cookie_secure(req_plain)

    # 2. Verified ASGI scheme https (e.g. from validated ProxyHeadersMiddleware) -> True
    https_scope = {
        "type": "http",
        "scheme": "https",
        "path": "/",
        "headers": [(b"host", b"localhost:8000")],
        "server": ("127.0.0.1", 8000),
    }
    req_https = Request(https_scope)
    assert cookie_secure(req_https)

    # 3. Explicit config MAIL_CORE_COOKIE_SECURE=1 -> True even for HTTP
    monkeypatch.setenv("MAIL_CORE_COOKIE_SECURE", "1")
    assert cookie_secure(req_plain)


def test_logout_fails_when_session_invalidation_fails(monkeypatch):
    """A37: Logout must return 500 (not success) if database session invalidation fails."""
    client = TestClient(app)
    login = client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD})
    csrf = login.json()["csrf_token"]

    def _broken_invalidate():
        raise AuthConfigError("DB failed during invalidate")

    monkeypatch.setattr("mail_core.api.auth_routes.invalidate_all_sessions", _broken_invalidate)
    out = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 500
    assert "failed to invalidate session in database" in out.json()["detail"]
