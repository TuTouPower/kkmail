"""A214: Account has no last_synced_at column — the hasattr branch is dead.

The timestamp belongs only in config["last_synced_at"]; the service must
not pretend to maintain a column attribute.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from mail_core.accounts.service import update_account_sync_status
from mail_core.mail.domain.enums import SyncStatus


class _FakeSession:
    def __init__(self, acc):
        self._acc = acc

    def get(self, _model, _pk):
        return self._acc

    def flush(self):
        pass


def test_update_account_sync_status_stores_timestamp_only_in_config():
    acc = SimpleNamespace(sync_status="idle", config={}, last_synced_at=None)
    result = update_account_sync_status(_FakeSession(acc), uuid.uuid4(), SyncStatus.IDLE)
    assert result is acc
    assert acc.sync_status == SyncStatus.IDLE.value
    assert "last_synced_at" in acc.config
    # no phantom column attribute is written
    assert acc.last_synced_at is None


def test_account_model_has_no_last_synced_at_column():
    from mail_core.mail.storage.models import Account

    assert "last_synced_at" not in Account.__table__.columns
