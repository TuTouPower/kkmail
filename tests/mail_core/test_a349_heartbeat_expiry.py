"""A349: heartbeat_lease must reject expired leases like assert_fencing.

Old heartbeat_lease only checked owner + fencing_token and then
extended the lease, so an expired-but-not-yet-stolen lease could be
revived by its old holder (reconcile uses heartbeat as the per-batch
fencing gate). assert_fencing already treats ``expires_at <= now`` as
a FencingMismatch; heartbeat now shares that rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from mail_core.sync.leases import FencingMismatch, heartbeat_lease

NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)


class _Session:
    def __init__(self, row):
        self.row = row
        self.flushed = False

    def execute(self, _stmt):
        row = self.row
        return SimpleNamespace(scalar_one_or_none=lambda: row)

    def flush(self):
        self.flushed = True


def _row(expires_at):
    return SimpleNamespace(
        owner_id="worker-1",
        fencing_token=7,
        lease_expires_at=expires_at,
        heartbeat_at=None,
    )


def test_heartbeat_rejects_expired_lease():
    row = _row(NOW - timedelta(seconds=1))
    session = _Session(row)
    with pytest.raises(FencingMismatch):
        heartbeat_lease(
            session,
            account_id=uuid.uuid4(),
            owner_id="worker-1",
            fencing_token=7,
            now=NOW,
        )
    # Not revived: expiry untouched and nothing flushed.
    assert row.lease_expires_at == NOW - timedelta(seconds=1)
    assert session.flushed is False


def test_heartbeat_rejects_lease_expiring_exactly_now():
    row = _row(NOW)
    with pytest.raises(FencingMismatch):
        heartbeat_lease(
            _Session(row),
            account_id=uuid.uuid4(),
            owner_id="worker-1",
            fencing_token=7,
            now=NOW,
        )


def test_heartbeat_rejects_expired_naive_lease():
    row = _row(datetime(2026, 10, 27, 11, 0, 0))  # naive, = 11:00 UTC < NOW
    with pytest.raises(FencingMismatch):
        heartbeat_lease(
            _Session(row),
            account_id=uuid.uuid4(),
            owner_id="worker-1",
            fencing_token=7,
            now=NOW,
        )


def test_heartbeat_renews_fresh_lease():
    row = _row(NOW + timedelta(seconds=10))
    session = _Session(row)
    handle = heartbeat_lease(
        session,
        account_id=uuid.uuid4(),
        owner_id="worker-1",
        fencing_token=7,
        ttl=timedelta(seconds=30),
        now=NOW,
    )
    assert row.lease_expires_at == NOW + timedelta(seconds=30)
    assert row.heartbeat_at == NOW
    assert handle.lease_expires_at == NOW + timedelta(seconds=30)
    assert session.flushed is True


def test_heartbeat_still_rejects_owner_and_token_mismatch():
    row = _row(NOW + timedelta(seconds=10))
    with pytest.raises(FencingMismatch):
        heartbeat_lease(
            _Session(row),
            account_id=uuid.uuid4(),
            owner_id="other-worker",
            fencing_token=7,
            now=NOW,
        )
    with pytest.raises(FencingMismatch):
        heartbeat_lease(
            _Session(row),
            account_id=uuid.uuid4(),
            owner_id="worker-1",
            fencing_token=8,
            now=NOW,
        )
