"""Test assert_fencing uses row lock to eliminate race conditions (SEC-07)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from mail_core.mail.storage.models import AccountSyncLease
from mail_core.sync.leases import FencingMismatch, assert_fencing


def test_assert_fencing_requests_for_update_lock():
    session = MagicMock()
    account_id = uuid.uuid4()
    lease_row = AccountSyncLease(account_id=account_id, fencing_token=1)
    session.get.return_value = lease_row

    # Valid token passes
    assert_fencing(session, account_id=account_id, fencing_token=1)

    session.get.assert_called_once_with(AccountSyncLease, account_id, with_for_update=True)

    # Token mismatch raises FencingMismatch
    with pytest.raises(FencingMismatch):
        assert_fencing(session, account_id=account_id, fencing_token=2)
