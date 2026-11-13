"""t079: session cookie Secure derives from the request scheme only.

MAIL_CORE_COOKIE_SECURE is removed (decision 20261113_cookie_secure_
scheme_derived supersedes A98): the Secure attribute is a fact about the
connection, not a configuration value. These tests pin the new semantics
-- including that a leftover env value must have no effect -- and close
the p078 black-box loop: over plain HTTP on a LAN hostname the issued
cookie must round-trip so /api/auth/me succeeds. TestClient's cookie jar
enforces the browser Secure rule (verified against the pre-fix
behaviour: with the env forcing Secure on, the same flow returned 401).
"""

from __future__ import annotations

from types import SimpleNamespace

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


def _fake_request(scheme: str):
    return SimpleNamespace(
        scope={"type": "http", "scheme": scheme, "headers": []},
        url=SimpleNamespace(scheme=scheme),
    )


def _cookie_attr_names(response) -> set[str]:
    raw = response.headers.get("set-cookie") or ""
    parts = [p.strip() for p in raw.split(";")]
    return {p.split("=", 1)[0].strip().lower() for p in parts[1:] if p}


# --- Unit: scheme derivation is the only input ---------------------------


def test_cookie_secure_http_false_even_when_env_forces_on(monkeypatch):
    from mail_core.security.auth import cookie_secure

    monkeypatch.setenv("MAIL_CORE_COOKIE_SECURE", "1")
    assert cookie_secure(_fake_request("http")) is False
    assert cookie_secure() is False


def test_cookie_secure_https_true_even_when_env_forces_off(monkeypatch):
    from mail_core.security.auth import cookie_secure

    monkeypatch.setenv("MAIL_CORE_COOKIE_SECURE", "0")
    assert cookie_secure(_fake_request("https")) is True


def test_cookie_secure_ignores_unvalidated_forwarded_proto():
    from starlette.requests import Request

    from mail_core.security.auth import cookie_secure

    scope = {
        "type": "http",
        "scheme": "http",
        "path": "/",
        "headers": [(b"x-forwarded-proto", b"https"), (b"host", b"localhost:8000")],
        "server": ("127.0.0.1", 8000),
    }
    assert cookie_secure(Request(scope)) is False


def test_cookie_samesite_none_follows_scheme_not_env(monkeypatch):
    from mail_core.security.auth import cookie_samesite

    monkeypatch.setenv("MAIL_CORE_COOKIE_SAMESITE", "none")
    # A leftover env value must not rescue SameSite=None over plain HTTP.
    monkeypatch.setenv("MAIL_CORE_COOKIE_SECURE", "1")
    assert cookie_samesite(_fake_request("http")) == "lax"
    assert cookie_samesite(_fake_request("https")) == "none"
    assert cookie_samesite() == "lax"


# --- Black-box: the p078 login loop over real entry shapes ---------------


LAN_HTTP_BASE = "http://karsondemacbook-pro.local:37281"
LAN_HTTPS_BASE = "https://karsondemacbook-pro.local"


def test_login_http_lan_host_roundtrip_despite_legacy_env(monkeypatch):
    """AC-001: http + LAN hostname login establishes a persistent session."""
    monkeypatch.setenv("MAIL_CORE_COOKIE_SECURE", "1")
    client = TestClient(app, base_url=LAN_HTTP_BASE)
    res = client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD})
    assert res.status_code == 200
    assert "secure" not in _cookie_attr_names(res)
    assert client.get("/api/auth/me").status_code == 200
    # Refresh: the session must persist on subsequent requests.
    assert client.get("/api/auth/me").status_code == 200


def test_login_https_sets_secure_cookie_despite_legacy_env(monkeypatch):
    """AC-002: https login issues a Secure cookie; the session round-trips."""
    monkeypatch.setenv("MAIL_CORE_COOKIE_SECURE", "0")
    client = TestClient(app, base_url=LAN_HTTPS_BASE)
    res = client.post("/api/auth/login", json={"password": TEST_LOGIN_PASSWORD})
    assert res.status_code == 200
    assert "secure" in _cookie_attr_names(res)
    assert client.get("/api/auth/me").status_code == 200
