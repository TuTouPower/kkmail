"""p056: Microsoft simplified onboarding — paste a redirect URL, exchange the code.

Unit tests cover URL parsing, the token/profile exchange with injected
transports, the env override, public-client connection validation, and the
API wiring with the account application service mocked. The full
mocked-Microsoft -> real-account chain is PG-gated and runs in CI.
"""
import os
import uuid

import pytest
from fastapi.testclient import TestClient

from mail_core.accounts import microsoft_oauth
from mail_core.accounts.connection import validate_connection
from mail_core.accounts.microsoft_oauth import (
    DEFAULT_MICROSOFT_CLIENT_ID,
    DEFAULT_MICROSOFT_REDIRECT_URI,
    exchange_redirect_url_for_tokens,
    parse_redirect_code,
)
from mail_core.api.app import app

REDIRECT = "http://localhost:8080/?code=ms-auth-code&state=random-state"


# --- parse_redirect_code -------------------------------------------------

def test_parse_redirect_code_valid_url():
    assert parse_redirect_code("http://localhost:8080/?code=abc123") == "abc123"


def test_parse_redirect_code_valid_url_with_state():
    assert parse_redirect_code(REDIRECT) == "ms-auth-code"


def test_parse_redirect_code_error_url_is_readable():
    with pytest.raises(ValueError, match="微软授权失败：用户取消了授权"):
        parse_redirect_code(
            "http://localhost:8080/?error=access_denied&error_description=用户取消了授权"
        )


def test_parse_redirect_code_error_url_without_description_falls_back_to_error():
    with pytest.raises(ValueError, match="微软授权失败：access_denied"):
        parse_redirect_code("http://localhost:8080/?error=access_denied")


def test_parse_redirect_code_missing_code():
    with pytest.raises(ValueError, match="未找到授权码"):
        parse_redirect_code("http://localhost:8080/?state=only-state")
    with pytest.raises(ValueError, match="未找到授权码"):
        parse_redirect_code("http://localhost:8080/")


# --- exchange_redirect_url_for_tokens ------------------------------------

def _fake_transports(captured, email="person@outlook.com"):
    def token_post(url, form):
        captured["token_url"] = url
        captured["form"] = dict(form)
        return {"access_token": "ms-access", "refresh_token": "ms-refresh", "expires_in": 3600}

    def profile_get(url, access_token):
        captured["profile_url"] = url
        captured["access_token"] = access_token
        return {"id": "ms-user", "mail": email, "userPrincipalName": "fallback@outlook.com"}

    return token_post, profile_get


def test_exchange_uses_public_client_form_and_returns_tokens_and_email():
    captured = {}
    token_post, profile_get = _fake_transports(captured)
    result = exchange_redirect_url_for_tokens(REDIRECT, token_post=token_post, profile_get=profile_get)
    assert captured["token_url"] == "https://login.microsoftonline.com/common/oauth2/v2.0/token"
    assert captured["form"] == {
        "client_id": DEFAULT_MICROSOFT_CLIENT_ID,
        "grant_type": "authorization_code",
        "code": "ms-auth-code",
        "redirect_uri": DEFAULT_MICROSOFT_REDIRECT_URI,
        "scope": microsoft_oauth.MICROSOFT_SCOPE,
    }
    assert "client_secret" not in captured["form"]
    assert captured["profile_url"] == "https://graph.microsoft.com/v1.0/me"
    assert captured["access_token"] == "ms-access"
    assert result["refresh_token"] == "ms-refresh"
    assert result["access_token"] == "ms-access"
    assert result["email"] == "person@outlook.com"
    assert result["client_id"] == DEFAULT_MICROSOFT_CLIENT_ID


def test_exchange_falls_back_to_user_principal_name():
    captured = {}
    token_post, _ = _fake_transports(captured)

    def profile_get(_url, _at):
        return {"id": "ms-user", "mail": None, "userPrincipalName": "UPN@Outlook.com"}

    result = exchange_redirect_url_for_tokens(REDIRECT, token_post=token_post, profile_get=profile_get)
    assert result["email"] == "upn@outlook.com"


def test_exchange_env_client_id_override(monkeypatch):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "env-override-client")
    captured = {}
    token_post, profile_get = _fake_transports(captured)
    result = exchange_redirect_url_for_tokens(REDIRECT, token_post=token_post, profile_get=profile_get)
    assert captured["form"]["client_id"] == "env-override-client"
    assert result["client_id"] == "env-override-client"


def test_exchange_explicit_client_id_beats_env(monkeypatch):
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "env-override-client")
    captured = {}
    token_post, profile_get = _fake_transports(captured)
    result = exchange_redirect_url_for_tokens(
        REDIRECT, "custom-client", token_post=token_post, profile_get=profile_get
    )
    assert captured["form"]["client_id"] == "custom-client"
    assert result["client_id"] == "custom-client"


def test_exchange_token_error_is_sanitized():
    def token_post(_url, _form):
        return {
            "error": "invalid_grant",
            "error_description": "AADSTS70000 code was already redeemed access_token=do-not-echo",
        }

    with pytest.raises(ValueError) as caught:
        exchange_redirect_url_for_tokens(REDIRECT, token_post=token_post, profile_get=lambda *_a: {})
    assert "do-not-echo" not in str(caught.value)
    assert "失效" in str(caught.value)


def test_exchange_missing_refresh_token_fails():
    def token_post(_url, _form):
        return {"access_token": "ms-access"}

    with pytest.raises(ValueError, match="Refresh Token"):
        exchange_redirect_url_for_tokens(REDIRECT, token_post=token_post, profile_get=lambda *_a: {})


# --- validate_connection public-client mode -------------------------------

def test_validate_connection_graph_public_client_without_secret_passes():
    validate_connection(
        "x@outlook.com", "graph", {"oauth_client_type": "public"},
        {"client_id": "any-public-client", "refresh_token": "r"},
    )


def test_validate_connection_graph_builtin_public_client_needs_no_secret_even_when_confidential():
    # Web deployments default to "confidential"; the built-in public client
    # has no secret by registration, so it must still validate.
    validate_connection(
        "x@outlook.com", "graph", {"oauth_client_type": "confidential"},
        {"client_id": DEFAULT_MICROSOFT_CLIENT_ID, "refresh_token": "r"},
    )


def test_validate_connection_graph_confidential_custom_client_still_requires_secret():
    with pytest.raises(ValueError, match="client_secret"):
        validate_connection(
            "x@example.test", "graph", {"oauth_client_type": "confidential"},
            {"client_id": "own-client", "refresh_token": "r"},
        )


def test_validate_connection_graph_with_secret_keeps_prior_requirements():
    # With a secret present the confidential path validates as before…
    validate_connection(
        "x@example.test", "graph", {"oauth_client_type": "confidential"},
        {"client_id": "own-client", "refresh_token": "r", "client_secret": "s"},
    )
    # …including the token_uri allowlist.
    with pytest.raises(ValueError, match="token_uri"):
        validate_connection(
            "x@example.test", "graph", {"oauth_client_type": "confidential"},
            {"client_id": "own-client", "refresh_token": "r", "client_secret": "s",
             "token_uri": "https://evil.example/token"},
        )


# --- exchange API (account service mocked; transports faked) ---------------

def _dto(email, group_id=None):
    from mail_core.mail.application.accounts import AccountDTO

    return AccountDTO(
        id=str(uuid.uuid4()), email=email, provider="graph", display_name=None,
        group_id=str(group_id) if group_id else None, group_name=None, group_color=None,
        status="active", sync_status="idle", sync_enabled=True, account_type="graph",
        remark=None, provider_profile="microsoft", oauth_client_type="public",
    )


def test_exchange_api_requires_auth():
    client = TestClient(app)
    response = client.post(
        "/api/accounts/oauth/exchange-redirect-url", json={"redirected_url": REDIRECT}
    )
    assert response.status_code == 401


def test_exchange_api_creates_graph_account_and_honors_group(api_client, monkeypatch):
    import mail_core.api.oauth_routes as routes

    created = {}

    def fake_create(**kwargs):
        created.update(kwargs)
        return _dto(kwargs["email"], kwargs.get("group_id"))

    monkeypatch.setattr(routes, "create_account_app", fake_create)
    monkeypatch.setattr(routes, "_find_graph_account_id", lambda _email: None)
    monkeypatch.setattr(routes, "_ensure_group_exists", lambda _gid: None)
    monkeypatch.setattr(
        routes,
        "exchange_redirect_url_for_tokens",
        lambda url, client_id=None: {
            "client_id": client_id or DEFAULT_MICROSOFT_CLIENT_ID,
            "access_token": "ms-access",
            "refresh_token": "ms-refresh",
            "email": "real@outlook.com",
        },
    )
    group_id = uuid.uuid4()
    response = api_client.post(
        "/api/accounts/oauth/exchange-redirect-url",
        json={
            "redirected_url": REDIRECT,
            # Mismatched form email: the Microsoft-returned email wins (spec
            # 4.3 step 3 choice — the token only belongs to that identity).
            "email": "typed-different@outlook.com",
            "group_id": str(group_id),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["email"] == "real@outlook.com"
    assert response.json()["provider"] == "graph"
    assert response.json()["group_id"] == str(group_id)
    assert created["email"] == "real@outlook.com"
    assert created["provider"] == "graph"
    assert created["group_id"] == group_id
    assert created["credentials"] == {
        "client_id": DEFAULT_MICROSOFT_CLIENT_ID, "refresh_token": "ms-refresh",
    }
    assert created["config"]["oauth_client_type"] == "public"
    assert created["config"]["provider_profile"] == "microsoft"
    assert "ms-access" not in response.text


def test_exchange_api_updates_existing_account(api_client, monkeypatch):
    import mail_core.api.oauth_routes as routes

    existing_id = uuid.uuid4()
    updated = {}

    def fake_update(account_id, **kwargs):
        updated["account_id"] = account_id
        updated.update(kwargs)
        return _dto("real@outlook.com", kwargs.get("group_id"))

    monkeypatch.setattr(routes, "update_account_app", fake_update)
    monkeypatch.setattr(routes, "_find_graph_account_id", lambda _email: existing_id)
    monkeypatch.setattr(routes, "_enqueue_sync_best_effort", lambda _aid: None)
    monkeypatch.setattr(
        routes,
        "exchange_redirect_url_for_tokens",
        lambda url, client_id=None: {
            "client_id": DEFAULT_MICROSOFT_CLIENT_ID,
            "access_token": "ms-access",
            "refresh_token": "fresh-refresh",
            "email": "real@outlook.com",
        },
    )
    response = api_client.post(
        "/api/accounts/oauth/exchange-redirect-url", json={"redirected_url": REDIRECT}
    )
    assert response.status_code == 200, response.text
    assert updated["account_id"] == existing_id
    assert updated["credentials"] == {
        "client_id": DEFAULT_MICROSOFT_CLIENT_ID, "refresh_token": "fresh-refresh",
    }
    assert updated["clear_credentials"] == ["client_secret"]


def test_exchange_api_parse_error_maps_to_readable_400(api_client):
    response = api_client.post(
        "/api/accounts/oauth/exchange-redirect-url",
        json={"redirected_url": "http://localhost:8080/?error=access_denied&error_description=用户取消"},
    )
    assert response.status_code == 400
    assert "微软授权失败：用户取消" in response.json()["detail"]


def test_exchange_api_missing_code_maps_to_readable_400(api_client):
    response = api_client.post(
        "/api/accounts/oauth/exchange-redirect-url",
        json={"redirected_url": "http://localhost:8080/"},
    )
    assert response.status_code == 400
    assert "未找到授权码" in response.json()["detail"]


def test_exchange_api_invalid_group_id_is_400(api_client, monkeypatch):
    import mail_core.api.oauth_routes as routes

    monkeypatch.setattr(
        routes,
        "exchange_redirect_url_for_tokens",
        lambda url, client_id=None: {
            "client_id": DEFAULT_MICROSOFT_CLIENT_ID, "access_token": "a",
            "refresh_token": "r", "email": "real@outlook.com",
        },
    )
    response = api_client.post(
        "/api/accounts/oauth/exchange-redirect-url",
        json={"redirected_url": REDIRECT, "group_id": "not-a-uuid"},
    )
    assert response.status_code == 400
    assert "分组" in response.json()["detail"]


# --- full chain against mocked Microsoft endpoints (PG) --------------------

@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="PG required")
def test_exchange_redirect_url_api_creates_graph_account_pg(api_client, monkeypatch):
    from sqlalchemy import select

    from mail_core.accounts import oauth_flow
    from mail_core.accounts.credentials import get_credential_store, load_json_secret
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import Account

    email = f"redirect-{uuid.uuid4().hex[:8]}@outlook.com"
    forms = []
    oauth_flow.set_oauth_http_hooks(
        token_post=lambda url, form: (forms.append((url, dict(form))), {
            "access_token": "opaque-ms-access", "refresh_token": "ms-refresh",
            "scope": microsoft_oauth.MICROSOFT_SCOPE, "expires_in": 3600,
        })[1],
        profile_get=lambda url, _at: {"id": "ms-user-1", "mail": email, "userPrincipalName": email},
    )
    group = api_client.post("/api/groups", json={"name": "redirect-group"})
    assert group.status_code == 200, group.text
    group_id = group.json()["id"]

    response = api_client.post(
        "/api/accounts/oauth/exchange-redirect-url",
        json={"redirected_url": REDIRECT, "group_id": group_id},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["email"] == email and data["provider"] == "graph"
    assert data["group_id"] == group_id
    assert "ms-refresh" not in response.text and "opaque-ms-access" not in response.text
    # Public-client exchange: no secret is ever sent to Microsoft.
    assert forms and "client_secret" not in forms[0][1]
    assert forms[0][1]["client_id"] == DEFAULT_MICROSOFT_CLIENT_ID
    with get_session_factory()() as db:
        row = db.scalar(select(Account).where(Account.email == email))
        assert row is not None and str(row.group_id) == group_id
        assert row.config["oauth_client_type"] == "public"
        assert row.config["provider_profile"] == "microsoft"
        creds = load_json_secret(get_credential_store(), row.credential_ref)
    assert creds == {"client_id": DEFAULT_MICROSOFT_CLIENT_ID, "refresh_token": "ms-refresh"}

    # Re-running with a fresh code updates the same account in place.
    oauth_flow.set_oauth_http_hooks(
        token_post=lambda _url, _form: {
            "access_token": "opaque-2", "refresh_token": "rotated-refresh",
            "scope": microsoft_oauth.MICROSOFT_SCOPE, "expires_in": 3600,
        },
        profile_get=lambda _url, _at: {"id": "ms-user-1", "mail": email},
    )
    again = api_client.post(
        "/api/accounts/oauth/exchange-redirect-url",
        json={"redirected_url": "http://localhost:8080/?code=second-code"},
    )
    assert again.status_code == 200, again.text
    assert again.json()["id"] == data["id"]
    with get_session_factory()() as db:
        row = db.scalar(select(Account).where(Account.email == email))
        creds = load_json_secret(get_credential_store(), row.credential_ref)
    assert creds["refresh_token"] == "rotated-refresh"
