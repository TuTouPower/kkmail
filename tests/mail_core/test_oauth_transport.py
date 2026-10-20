"""OAuth refresh + Bearer transport (mocked token endpoint)."""

from __future__ import annotations

import json
import time

import pytest

from mail_core.accounts import DictCredentialStore
from mail_core.mail.storage.models import Account
from mail_core.providers.factory import build_provider
from mail_core.providers.gmail import GmailNotConfiguredError, GmailProvider
from mail_core.providers.graph import GraphNotConfiguredError
from mail_core.providers.http import ProviderHttpError
from mail_core.providers.oauth import (
    BearerTransport,
    OAuthError,
    OAuthTokenClient,
)


def test_refresh_token_grant_persists_access_token():
    store = DictCredentialStore(
        {
            "oauth:gmail": json.dumps(
                {
                    "refresh_token": "rt-1",
                    "client_id": "cid",
                    "client_secret": "sec",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            )
        }
    )
    calls = []

    def token_post(method, url, form, headers):
        calls.append((method, url, dict(form)))
        assert form["grant_type"] == "refresh_token"
        assert form["refresh_token"] == "rt-1"
        return {"access_token": "at-1", "expires_in": 3600, "token_type": "Bearer"}

    client = OAuthTokenClient(
        credential_ref="oauth:gmail",
        store=store,
        provider="gmail",
        http_post=token_post,
    )
    assert client.get_access_token() == "at-1"
    assert len(calls) == 1
    # Second call uses cache
    assert client.get_access_token() == "at-1"
    assert len(calls) == 1
    saved = json.loads(store.get_secret("oauth:gmail"))
    assert saved["access_token"] == "at-1"
    assert saved["expires_at"] > time.time()


def test_bearer_transport_attaches_header_and_retries_401():
    store = DictCredentialStore(
        {
            "oauth:g": json.dumps(
                {
                    "refresh_token": "rt",
                    "client_id": "c",
                    "client_secret": "s",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "access_token": "stale",
                    "expires_at": time.time() + 9999,
                }
            )
        }
    )
    tokens = {"n": 0}

    def token_post(method, url, form, headers):
        tokens["n"] += 1
        return {"access_token": f"fresh-{tokens['n']}", "expires_in": 3600}

    client = OAuthTokenClient(credential_ref="oauth:g", store=store, provider="gmail", http_post=token_post)
    seen = []

    def api(method, url, params, headers):
        seen.append(headers.get("Authorization"))
        if headers.get("Authorization") == "Bearer stale":
            raise ProviderHttpError("unauthorized", status=401)
        return {
            "history": [],
            "historyId": "9",
        }

    transport = BearerTransport(token_client=client, inner=api, base_url="https://gmail.googleapis.com")
    p = GmailProvider(credential_ref="oauth:g", transport=transport)
    page = p.delta_changes("INBOX", {"historyId": "1"})
    assert page.exhausted
    assert seen[0] == "Bearer stale"
    assert seen[1].startswith("Bearer fresh-")
    assert tokens["n"] == 1


def test_factory_wires_gmail_oauth_and_not_configured_without_ref():
    store = DictCredentialStore(
        {
            "oauth:gmail": json.dumps(
                {
                    "refresh_token": "rt",
                    "client_id": "c",
                    "client_secret": "s",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            )
        }
    )

    def token_post(method, url, form, headers):
        return {"access_token": "tok", "expires_in": 3600}

    api_calls = []

    def api(method, url, params, headers):
        api_calls.append((method, url, headers.get("Authorization")))
        assert headers["Authorization"] == "Bearer tok"
        return {
            "@odata.deltaLink": "https://graph/delta?t=1",
            "value": [],
        }

    acc = Account(email="a@g.com", provider="gmail", credential_ref="oauth:gmail")
    provider = build_provider(acc, store, token_http=token_post, api_http=api)
    out = provider.delta_changes("INBOX", {"historyId": "1"})
    assert out.exhausted
    assert api_calls and "Bearer tok" in api_calls[0][2]

    bare = Account(email="b@g.com", provider="gmail", credential_ref="")
    with pytest.raises(GmailNotConfiguredError):
        build_provider(bare, store).delta_changes("INBOX", {"historyId": "1"})


def test_factory_wires_graph_oauth():
    store = DictCredentialStore(
        {
            "oauth:graph": json.dumps(
                {
                    "refresh_token": "rt",
                    "client_id": "c",
                    "client_secret": "s",
                    "token_uri": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
                }
            )
        }
    )

    def token_post(method, url, form, headers):
        return {"access_token": "gtok", "expires_in": 3600}

    def api(method, url, params, headers):
        assert "Bearer gtok" in headers["Authorization"]
        return {"@odata.deltaLink": "https://graph/delta?x=1", "value": []}

    acc = Account(email="a@outlook.com", provider="graph", credential_ref="oauth:graph")
    provider = build_provider(acc, store, token_http=token_post, api_http=api)
    page = provider.delta_changes("inbox", {})
    assert page.exhausted and page.next_cursor["delta_link"].endswith("x=1")


def test_oauth_error_on_token_failure():
    store = DictCredentialStore(
        {"oauth:x": json.dumps({"refresh_token": "rt", "client_id": "c", "token_uri": "https://t"})}
    )

    def token_post(method, url, form, headers):
        return {"error": "invalid_grant", "error_description": "revoked"}

    client = OAuthTokenClient(credential_ref="oauth:x", store=store, provider="gmail", http_post=token_post)
    with pytest.raises(OAuthError):
        client.get_access_token()


def test_keyring_store_has_no_silent_memory_fallback(monkeypatch):
    import builtins

    from mail_core.accounts import KeyringCredentialStore

    real_import = builtins.__import__

    def no_keyring(name, *a, **kw):
        if name == "keyring":
            raise ImportError("no keyring")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", no_keyring)
    store = KeyringCredentialStore()
    with pytest.raises(RuntimeError, match="keyring"):
        store.put_secret("keyring:test/user", '{"a":1}')


def test_env_store_is_read_only(monkeypatch):
    from mail_core.accounts import EnvCredentialStore, ReadOnlyCredentialRef

    monkeypatch.setenv("KK_TEST_SECRET", "s3cret")
    store = EnvCredentialStore()
    assert store.get_secret("env:KK_TEST_SECRET") == "s3cret"
    with pytest.raises(ReadOnlyCredentialRef):
        store.put_secret("env:KK_TEST_SECRET", "other")
    assert store.get_secret("env:KK_TEST_SECRET") == "s3cret"
