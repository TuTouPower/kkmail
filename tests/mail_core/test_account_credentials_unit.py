"""Unit tests for atomicity between account operations and credentials (PROV-06)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from mail_core.accounts.service import create_account, delete_account, update_account
from mail_core.mail.storage.models import Account


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
    mock_session.get.return_value = mock_acc

    with patch("mail_core.accounts.service.get_credential_store", return_value=mock_store):
        # 1. create_account
        acc = create_account(
            mock_session,
            email="test@example.com",
            provider="imap",
            credentials={"password": "pwd1"},
        )
        assert mock_store.put_secret.called
        # Check that session=mock_session was passed in kwargs
        _, kwargs = mock_store.put_secret.call_args
        assert kwargs.get("session") is mock_session

        mock_store.reset_mock()

        # 2. update_account
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
