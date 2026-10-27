"""A165: validate_connection must whitelist the provider and reject
credential keys outside the provider's own field set.

Previously an unknown provider fell through every check (``provider not in
CREDENTIAL_FIELDS`` short-circuited credential validation), and an imap
credential set could carry graph-only keys such as token_uri without any
rejection.
"""

from __future__ import annotations

import pytest

from mail_core.accounts.connection import validate_connection


@pytest.fixture(autouse=True)
def _allow_private_hosts(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")


def test_unknown_provider_is_rejected():
    with pytest.raises(ValueError, match="provider"):
        validate_connection("a@example.test", "carrier-pigeon", {}, {"password": "p"})


def test_unknown_provider_is_rejected_even_without_credential_requirement():
    with pytest.raises(ValueError, match="provider"):
        validate_connection(
            "a@example.test", "carrier-pigeon", {}, None, require_credentials=False
        )


def test_imap_rejects_graph_only_token_uri_credential():
    with pytest.raises(ValueError, match="token_uri"):
        validate_connection(
            "a@example.test",
            "imap",
            {"imap_host": "imap.example.test"},
            {"password": "p", "token_uri": "https://evil.example.test/token"},
        )
    # Even a well-formed Microsoft token_uri is not an imap credential key.
    with pytest.raises(ValueError, match="token_uri"):
        validate_connection(
            "a@example.test",
            "imap",
            {"imap_host": "imap.example.test"},
            {
                "password": "p",
                "token_uri": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
            },
        )


def test_imap_rejects_other_out_of_set_credential_keys():
    with pytest.raises(ValueError, match="client_secret"):
        validate_connection(
            "a@example.test",
            "imap",
            {"imap_host": "imap.example.test"},
            {"password": "p", "client_secret": "nope"},
        )


def test_graph_rejects_imap_only_password_key():
    with pytest.raises(ValueError, match="password"):
        validate_connection(
            "a@example.test",
            "graph",
            {"oauth_client_type": "public"},
            {"client_id": "id", "refresh_token": "r", "password": "p"},
        )


def test_graph_token_uri_still_restricted_to_microsoft_https_endpoints():
    with pytest.raises(ValueError, match="token_uri"):
        validate_connection(
            "a@example.test",
            "graph",
            {"oauth_client_type": "public"},
            {
                "client_id": "id",
                "refresh_token": "r",
                "token_uri": "https://evil.example.test/token",
            },
        )
    # A legitimate Microsoft endpoint passes.
    validate_connection(
        "a@example.test",
        "graph",
        {"oauth_client_type": "public"},
        {
            "client_id": "id",
            "refresh_token": "r",
            "token_uri": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        },
    )


@pytest.mark.parametrize("provider", ["stub", "memory"])
def test_internal_test_providers_are_explicitly_allowed(provider):
    # Internal test providers are whitelisted explicitly; they take no
    # credential contract and must not be rejected as unknown.
    validate_connection("a@example.test", provider, {}, None, require_credentials=False)


def test_graph_runtime_cache_keys_remain_accepted():
    # Stored graph credentials legitimately carry the runtime access-token
    # cache keys written by the OAuth layer itself.
    validate_connection(
        "a@example.test",
        "graph",
        {"oauth_client_type": "public"},
        {
            "client_id": "id",
            "refresh_token": "r",
            "access_token": "cached",
            "expires_at": 9999999999,
        },
    )
