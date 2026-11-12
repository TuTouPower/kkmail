"""A218 / t076: _query_inbox_stats must not carry恒假 branches.

The aggregate filters ``Account.sync_enabled.is_(True)`` in SQL, so
the per-row ``if not values["sync_enabled"]: continue`` could never
fire and the ``not sync_enabled`` arm of is_faulty_without_target was
equally dead. Both are removed. The faulty-account arm now reads the
orthogonal health columns ``credential_state`` / ``connectivity_state``
(an invalid credential or a tripped transport breaker without a target
folder stays out of the active total) and is pinned below.
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


def _row(
    *,
    folder_count=0,
    stats_count=0,
    unread=None,
    total=None,
    known=0,
    credential_state="valid",
    connectivity_state="connected",
):
    # t076: queries.py 读取 credential_state 与 connectivity_state 两个键；
    # 旧 sync_status 单列已移除。
    return SimpleNamespace(
        _mapping={
            "account_id": uuid.uuid4(),
            "folder_count": folder_count,
            "stats_count": stats_count,
            "unread_count": unread,
            "total_count": total,
            "known_unread_count": known,
            "sync_enabled": True,
            "credential_state": credential_state,
            "connectivity_state": connectivity_state,
        }
    )


def test_no_dead_sync_enabled_branches_remain():
    source = inspect.getsource(_query_inbox_stats)
    assert 'if not values["sync_enabled"]' not in source
    assert "not sync_enabled" not in source


def test_unreachable_account_without_inbox_folder_stays_out_of_total():
    # t076: 旧 sync_status="failed"（网络故障）→ connectivity_state="unreachable"。
    rows = [
        _row(folder_count=1, stats_count=1, unread=5, total=9, known=1),
        _row(connectivity_state="unreachable"),
    ]
    result = _query_inbox_stats(_FakeSession(rows), folder_role="inbox", group_id=None)
    assert len(result.accounts) == 2
    assert result.total_unread == 5


def test_invalid_credential_account_without_folder_also_excluded_from_total():
    # t076: 旧 sync_status="auth_failed" → credential_state="invalid"。
    rows = [_row(credential_state="invalid")]
    result = _query_inbox_stats(_FakeSession(rows), folder_role="inbox", group_id=None)
    assert len(result.accounts) == 1
    assert result.total_unread == 0


def test_healthy_account_without_folder_keeps_total_unknown():
    # t076: 旧 sync_status="idle" → 默认 valid/connected。
    rows = [
        _row(folder_count=1, stats_count=1, unread=5, total=9, known=1),
        _row(),
    ]
    result = _query_inbox_stats(_FakeSession(rows), folder_role="inbox", group_id=None)
    assert result.total_unread is None
