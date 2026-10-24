import logging
from types import SimpleNamespace

import pytest

from mail_core.providers.factory import build_provider


def _build_account(host: str, use_ssl: bool):
    account = SimpleNamespace(
        email="user@example.test",
        provider="imap",
        credential_ref="credential-ref",
        config={"imap_host": host, "use_ssl": use_ssl},
    )
    store = SimpleNamespace(get_secret=lambda _ref: "test-password")
    return build_provider(account, store, timeout=5.0)


def test_plaintext_imap_rejects_non_loopback_hosts(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")

    with pytest.raises(ValueError, match="loopback"):
        _build_account("imap.example.test", use_ssl=False)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_plaintext_imap_allows_loopback_with_warning(monkeypatch, caplog, host):
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")

    with caplog.at_level(logging.WARNING, logger="mail_core.providers.factory"):
        provider = _build_account(host, use_ssl=False)

    assert provider.use_ssl is False
    assert "plaintext IMAP" in caplog.text


def test_tls_imap_accepts_non_loopback_host(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_ALLOW_PRIVATE_HOSTS", "1")

    provider = _build_account("imap.example.test", use_ssl=True)

    assert provider.use_ssl is True
