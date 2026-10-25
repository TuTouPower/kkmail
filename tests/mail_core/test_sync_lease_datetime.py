from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

import pytest

from mail_core.sync.leases import FencingMismatch, assert_fencing


class _Session:
    def __init__(self, row):
        self.row = row

    def get(self, _model, _account_id, *, with_for_update):
        assert with_for_update is True
        return self.row


def test_assert_fencing_normalizes_naive_expiry_to_utc():
    row = SimpleNamespace(
        fencing_token=3,
        lease_expires_at=datetime(2026, 1, 1, 10, 0),
    )

    assert_fencing(
        _Session(row),
        account_id=uuid.uuid4(),
        fencing_token=3,
        now=datetime(2026, 1, 1, 9, 30, tzinfo=timezone.utc),
    )


def test_assert_fencing_rejects_expired_naive_expiry():
    row = SimpleNamespace(
        fencing_token=3,
        lease_expires_at=datetime(2026, 1, 1, 10, 0),
    )

    with pytest.raises(FencingMismatch):
        assert_fencing(
            _Session(row),
            account_id=uuid.uuid4(),
            fencing_token=3,
            now=datetime(2026, 1, 1, 11, 0, tzinfo=timezone.utc),
        )
