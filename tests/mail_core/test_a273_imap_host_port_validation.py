"""A273: IMAP host/port come from DB JSON config and must be validated for
type and range, failing with field-named ValueErrors."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mail_core.accounts.credentials import DictCredentialStore
from mail_core.mail.storage.models import Account
from mail_core.providers.factory import build_provider

STORE = DictCredentialStore({"ref": {"password": "pw"}})


def _build(config: dict):
    account = Account(
        email="a@b.com",
        provider="imap",
        credential_ref="ref",
        config=config,
    )
    with patch("mail_core.providers.factory.validate_imap_host", lambda _h: None):
        return build_provider(account, STORE, timeout=5.0)


@pytest.mark.parametrize("host", [123, 9.9, ["imap.example.test"], {"h": 1}, "", "   ", None])
def test_invalid_host_raises_field_named_value_error(host):
    with pytest.raises(ValueError, match="imap_host"):
        _build({"imap_host": host, "imap_port": 993})


@pytest.mark.parametrize("port", ["abc", "99.5", 993.7, True, 0, -1, 65536, 100000])
def test_invalid_port_raises_field_named_value_error(port):
    with pytest.raises(ValueError, match="imap_port"):
        _build({"imap_host": "imap.example.test", "imap_port": port})


def test_valid_host_and_port_forms_still_work():
    provider = _build({"imap_host": "imap.example.test", "imap_port": 993})
    assert (provider.host, provider.port) == ("imap.example.test", 993)
    provider = _build({"imap_host": "imap.example.test", "imap_port": "993"})
    assert provider.port == 993
    # Fallback keys (host/port) work; plaintext requires a loopback host.
    provider = _build({"host": "127.0.0.1", "port": 143, "use_ssl": False})
    assert (provider.host, provider.port) == ("127.0.0.1", 143)


def test_default_ports_unchanged():
    provider = _build({"imap_host": "imap.example.test"})
    assert provider.port == 993
