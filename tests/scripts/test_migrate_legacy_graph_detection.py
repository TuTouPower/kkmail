"""A133: Graph detection must use exact domain matching, not substring."""

from __future__ import annotations

import pytest

from scripts.migrate_from_legacy_db import legacy_account_connection


def _row(email, *, auth_type="", refresh_token="", imap_host="imap.example.test", record_id=7):
    return {
        "id": record_id,
        "email": email,
        "authorization_type": auth_type,
        "refresh_token": refresh_token,
        "imap_host": imap_host,
        "imap_port": 993,
    }


def test_explicit_graph_authorization_type_wins_for_any_domain():
    assert legacy_account_connection(_row("user@company.example", auth_type="graph")) == (
        "graph",
        {},
    )


@pytest.mark.parametrize(
    "email",
    [
        "user@outlook.com",
        "user@hotmail.com",
        "user@live.co.uk",
        "User@OUTLOOK.COM",
        "user@outlook.com.",
    ],
)
def test_refresh_token_with_exact_microsoft_domain_is_graph(email):
    assert legacy_account_connection(_row(email, refresh_token="rt")) == ("graph", {})


@pytest.mark.parametrize(
    "email",
    [
        "outlook@example.com",
        "foo@outlook.example.com",
        "user@outlook.com.evil.example",
        "user@notoutlook.com",
    ],
)
def test_refresh_token_with_non_microsoft_domain_is_an_operator_error(email):
    with pytest.raises(ValueError, match="authorization_type"):
        legacy_account_connection(_row(email, refresh_token="rt"))


def test_unknown_authorization_type_is_an_operator_error():
    with pytest.raises(ValueError, match="authorization_type"):
        legacy_account_connection(_row("user@example.com", auth_type="oauth-legacy", refresh_token="rt"))


def test_no_refresh_token_falls_through_to_imap():
    provider, config = legacy_account_connection(_row("user@example.com"))

    assert provider == "imap"
    assert config["imap_host"] == "imap.example.test"


def test_explicit_imap_with_microsoft_domain_is_still_rejected():
    with pytest.raises(ValueError):
        legacy_account_connection(
            _row("user@outlook.com", auth_type="imap", refresh_token="rt")
        )
