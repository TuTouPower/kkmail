"""A218: _query_inbox_stats must not carry恒假 branches.

The aggregate filters ``Account.sync_enabled.is_(True)`` in SQL, so
the per-row ``if not values["sync_enabled"]: continue`` could never
fire and the ``not sync_enabled`` arm of is_faulty_without_target was
equally dead. Both are removed; the sync_status arm (failed /
auth_failed accounts without an inbox folder stay out of the active
total) is the live判定 and is pinned behaviourally below.
"""

from __future__ import annotations

import inspect
import uuid
from types import SimpleNamespace

from mail_core.mail.application import queries
from mail_core.mail.application.queries import _query_inbox_stats


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _stmt):
        return _Result(self._rows)


def _row(*, folder_count=0, stats_count=0, unread=None, total=None, known=0, sync_status="idle"):
    return SimpleNamespace(
        _mapping={
            "account_id": uuid.uuid4(),
            "folder_count": folder_count,
            "stats_count": stats_count,
            "unread_count": unread,
            "total_count": total,
            "known_unread_count": known,
            "sync_enabled": True,
            "sync_status": sync_status,
        }
    )


def test_no_dead_sync_enabled_branches_remain():
    source = inspect.getsource(_query_inbox_stats)
    assert 'if not values["sync_enabled"]' not in source
    assert "not sync_enabled" not in source


def test_failed_account_without_inbox_folder_stays_out_of_total():
    rows = [
        _row(folder_count=1, stats_count=1, unread=5, total=9, known=1),
        _row(sync_status="failed"),  # enabled (SQL filter), no folder yet
    ]
    result = _query_inbox_stats(_FakeSession(rows), folder_role="inbox", group_id=None)
    assert len(result.accounts) == 2
    assert result.total_unread == 5


def test_auth_failed_account_without_folder_also_excluded_from_total():
    rows = [_row(sync_status="auth_failed")]
    result = _query_inbox_stats(_FakeSession(rows), folder_role="inbox", group_id=None)
    assert len(result.accounts) == 1
    assert result.total_unread == 0


def test_idle_account_without_folder_keeps_total_unknown():
    rows = [
        _row(folder_count=1, stats_count=1, unread=5, total=9, known=1),
        _row(sync_status="idle"),
    ]
    result = _query_inbox_stats(_FakeSession(rows), folder_role="inbox", group_id=None)
    assert result.total_unread is None
