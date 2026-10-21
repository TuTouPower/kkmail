"""Test assert_fencing uses row lock to eliminate race conditions (SEC-07)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid
from unittest.mock import MagicMock

import pytest

from mail_core.mail.storage.models import AccountSyncLease
from mail_core.sync.leases import FencingMismatch, assert_fencing, release_lease


def test_assert_fencing_requests_for_update_lock():
    session = MagicMock()
    account_id = uuid.uuid4()
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    lease_row = AccountSyncLease(account_id=account_id, fencing_token=1, lease_expires_at=future)
    session.get.return_value = lease_row

    # Valid token passes
    assert_fencing(session, account_id=account_id, fencing_token=1)

    session.get.assert_called_once_with(AccountSyncLease, account_id, with_for_update=True)

    # Token mismatch raises FencingMismatch
    with pytest.raises(FencingMismatch):
        assert_fencing(session, account_id=account_id, fencing_token=2)

    # Expired lease raises FencingMismatch
    lease_row.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(FencingMismatch):
        assert_fencing(session, account_id=account_id, fencing_token=1)


def test_release_lease_advances_fencing_token():
    session = MagicMock()
    account_id = uuid.uuid4()
    lease_row = AccountSyncLease(
        account_id=account_id,
        owner_id="worker_1",
        fencing_token=1,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
    )
    session.execute.return_value.scalar_one_or_none.return_value = lease_row

    release_lease(session, account_id=account_id, owner_id="worker_1", fencing_token=1)
    assert lease_row.fencing_token == 2

