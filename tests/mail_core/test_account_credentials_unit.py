"""Unit tests for atomicity between account operations and credentials (PROV-06)."""

from __future__ import annotations

import json
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest

from mail_core.accounts.credentials import (
    CompositeCredentialStore,
    DictCredentialStore,
    EnvCredentialStore,
    credential_edit,
    save_json_secret,
)
from mail_core.accounts.service import create_account, delete_account, update_account
from mail_core.mail.storage.models import Account


def test_create_account_validates_missing_imap_config():
    with (
        patch("mail_core.accounts.service.lock_sidebar_layout"),
        pytest.raises(ValueError, match="config.imap_host: required"),
    ):
        create_account(MagicMock(), email="user@example.com", provider="imap")


def test_create_and_update_and_delete_account_passes_session_to_credential_store():
    mock_session = MagicMock()
    mock_store = MagicMock()

    acc_id = uuid.uuid4()
    mock_acc = Account(
        id=acc_id,
        email="user@example.com",
        provider="imap",
        credential_ref="account:123",
    )
    mock_acc.config = {"imap_host": "imap.example.test"}
    mock_session.get.return_value = mock_acc
    mock_session.scalar.return_value = None
    mock_store.get_secret.return_value = '{"password": "old"}'

    with patch("mail_core.accounts.service.get_credential_store", return_value=mock_store):
        # 1. create_account
        acc = create_account(
            mock_session,
            email="test@example.com",
            provider="imap",
            config={"imap_host": "8.8.8.8"},
            credentials={"password": "pwd1"},
        )
        assert mock_store.put_secret.called
        # Check that session=mock_session was passed in kwargs
        _, kwargs = mock_store.put_secret.call_args
        assert kwargs.get("session") is mock_session

        mock_store.reset_mock()

        # 2. update_account
        mock_session.scalar.return_value = mock_acc
        with patch("mail_core.providers.factory.validate_imap_host"):
            update_account(
            mock_session,
            acc_id,
            credentials={"password": "new_pwd"},
        )
        assert mock_store.put_secret.called
        _, kwargs = mock_store.put_secret.call_args
        assert kwargs.get("session") is mock_session

        mock_store.reset_mock()

        # 3. delete_account
        delete_account(mock_session, acc_id)
        assert mock_store.delete_secret.called
        _, kwargs = mock_store.delete_secret.call_args
        assert kwargs.get("session") is mock_session


def test_credential_edit_persists_nested_mutations():
    store = DictCredentialStore({"oauth-flow": '{"token": {"access": "old"}}'})

    with credential_edit(store, "oauth-flow") as data:
        data["token"]["access"] = "new"

    assert json.loads(store.get_secret("oauth-flow")) == {"token": {"access": "new"}}


class _SessionAwareCredentialStore:
    def __init__(self):
        self.put_calls = []
        self.delete_calls = []

    def get_secret(self, credential_ref):
        raise KeyError(credential_ref)

    def put_secret(self, credential_ref, secret, *, session=None):
        self.put_calls.append((credential_ref, secret, session))
        raise TypeError("store implementation failed")

    def delete_secret(self, credential_ref, *, session=None):
        self.delete_calls.append((credential_ref, session))
        raise TypeError("store implementation failed")


class _LegacyCredentialStore:
    def __init__(self):
        self.put_calls = []
        self.delete_calls = []

    def get_secret(self, credential_ref):
        raise KeyError(credential_ref)

    def put_secret(self, credential_ref, secret):
        self.put_calls.append((credential_ref, secret))

    def delete_secret(self, credential_ref):
        self.delete_calls.append(credential_ref)


def test_composite_propagates_store_typeerror_without_retry():
    target = _SessionAwareCredentialStore()
    store = CompositeCredentialStore(db=target)
    session = object()

    with pytest.raises(TypeError, match="store implementation failed"):
        store.put_secret("account:one", "secret", session=session)
    with pytest.raises(TypeError, match="store implementation failed"):
        store.delete_secret("account:one", session=session)

    assert target.put_calls == [("account:one", "secret", session)]
    assert target.delete_calls == [("account:one", session)]


def test_composite_omits_session_for_legacy_store_signatures():
    target = _LegacyCredentialStore()
    store = CompositeCredentialStore(env=target)

    store.put_secret("env:SECRET", "secret", session=object())
    store.delete_secret("env:SECRET", session=object())

    assert target.put_calls == [("env:SECRET", "secret")]
    assert target.delete_calls == ["env:SECRET"]


def test_save_json_secret_does_not_retry_internal_typeerror():
    target = _SessionAwareCredentialStore()
    session = object()

    with pytest.raises(TypeError, match="store implementation failed"):
        save_json_secret(target, "account:one", {"token": "value"}, session=session)

    assert target.put_calls == [("account:one", '{"token": "value"}', session)]


def test_save_json_secret_omits_session_for_legacy_store_signature():
    target = _LegacyCredentialStore()

    save_json_secret(target, "account:one", {"token": "value"}, session=object())

    assert target.put_calls == [("account:one", '{"token": "value"}')]


def test_credential_edit_allows_readonly_environment_secret(monkeypatch):
    monkeypatch.setenv("OAUTH_SECRET", '{"access_token": "old"}')

    with credential_edit(
        EnvCredentialStore(),
        "env:OAUTH_SECRET",
        allow_readonly=True,
    ) as data:
        data["access_token"] = "rotated"

    assert json.loads(os.environ["OAUTH_SECRET"]) == {"access_token": "old"}
