"""OAuth token_uri allowlist + expires_at must not mean forever-valid."""

from __future__ import annotations

import json
import time

import pytest

from mail_core.accounts.credentials import DictCredentialStore
from mail_core.providers.oauth import OAuthError, OAuthTokenClient


def test_token_uri_rejects_ssrf_target():
    store = DictCredentialStore()
    store.put_secret(
        "ref",
        json.dumps(
            {
                "refresh_token": "r",
                "client_id": "c",
                "token_uri": "http://169.254.169.254/latest/meta-data",
                "access_token": "t",
                "expires_at": time.time() + 3600,
            }
        ),
    )
    client = OAuthTokenClient(credential_ref="ref", store=store, provider="gmail")
    with pytest.raises(OAuthError, match="allowlist"):
        client.token_uri()


def test_missing_expires_at_forces_refresh():
    store = DictCredentialStore()
    store.put_secret(
        "ref",
        json.dumps({"refresh_token": "r", "client_id": "c", "access_token": "cached"}),
    )
    client = OAuthTokenClient(credential_ref="ref", store=store, provider="gmail")
    assert client._access_valid(client._load()) is False


def test_allowlisted_google_uri_ok():
    store = DictCredentialStore()
    store.put_secret(
        "ref",
        json.dumps(
            {
                "refresh_token": "r",
                "client_id": "c",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        ),
    )
    client = OAuthTokenClient(credential_ref="ref", store=store, provider="gmail")
    assert client.token_uri().startswith("https://oauth2.googleapis.com/")


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("gmail", "https://oauth2.googleapis.com/token"),
        ("graph", "https://login.microsoftonline.com/common/oauth2/v2.0/token"),
    ],
)
def test_missing_token_uri_uses_allowlisted_provider_default(provider, expected):
    store = DictCredentialStore()
    store.put_secret("ref", json.dumps({"refresh_token": "r", "client_id": "c"}))
    client = OAuthTokenClient(credential_ref="ref", store=store, provider=provider)

    assert client.token_uri() == expected
