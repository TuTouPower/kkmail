"""A248: dict-shaped IMAP credentials missing password must raise, matching
the JSON-string shape (which already raises "credential JSON missing password")."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from mail_core.accounts.credentials import DictCredentialStore
from mail_core.mail.storage.models import Account
from mail_core.providers.factory import build_provider


def _account() -> Account:
    return Account(
        email="a@b.com",
        provider="imap",
        credential_ref="ref",
        config={"imap_host": "imap.example.test", "imap_port": 993},
    )


def test_dict_secret_without_password_or_secret_raises():
    store = DictCredentialStore({"ref": {"username": "a@b.com"}})
    with patch("mail_core.providers.factory.validate_imap_host", lambda _h: None):
        with pytest.raises(ValueError, match="credential JSON missing password"):
            build_provider(_account(), store, timeout=5.0)


def test_dict_secret_with_empty_password_raises():
    store = DictCredentialStore({"ref": {"password": "", "secret": ""}})
    with patch("mail_core.providers.factory.validate_imap_host", lambda _h: None):
        with pytest.raises(ValueError, match="credential JSON missing password"):
            build_provider(_account(), store, timeout=5.0)


def test_dict_secret_with_secret_alias_still_works():
    store = DictCredentialStore({"ref": {"secret": "alias-pw"}})
    with patch("mail_core.providers.factory.validate_imap_host", lambda _h: None):
        provider = build_provider(_account(), store, timeout=5.0)
    assert provider.password == "alias-pw"
