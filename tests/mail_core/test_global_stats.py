"""Global/group inbox stats read model — real-DB version (T4).

The query tests previously fed query_global_inbox_stats /
query_group_inbox_stats a MagicMock session whose execute().all()
returned hand-built _mapping rows, so the aggregate SQL (outer joins,
sync_enabled filter, NULL-counter semantics) never ran. They now run
against real PostgreSQL rows; per-test table truncation comes from
the shared runtime_isolation fixture. The API test still patches the
query function on purpose: it covers HTTP serialization only.
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.application.queries import GlobalStatsOut, query_global_inbox_stats, query_group_inbox_stats
from mail_core.mail.storage.models import Account, AccountGroup, Folder, FolderStats
from tests.mail_core.conftest import TEST_API_KEY

requires_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set (PG-gated real-DB test)",
)


def _account(session, *, sync_enabled=True, sync_status="idle", group_id=None) -> Account:
    acc = Account(
        email=f"stats-{uuid.uuid4().hex[:10]}@example.com",
        provider="imap",
        sync_enabled=sync_enabled,
        sync_status=sync_status,
        group_id=group_id,
    )
    session.add(acc)
    session.flush()
    return acc


def _inbox(session, account: Account, *, unread, total) -> Folder:
    folder = Folder(
        account_id=account.id,
        remote_id=f"INBOX-{uuid.uuid4().hex[:8]}",
        name="INBOX",
        role="inbox",
    )
    session.add(folder)
    session.flush()
    session.add(FolderStats(folder_id=folder.id, unread_count=unread, total_count=total))
    session.flush()
    return folder


def _by_id(result) -> dict:
    return {a.account_id: a for a in result.accounts}


@requires_db
def test_query_global_inbox_stats_excludes_disabled_accounts_and_keeps_enabled_sync_failures():
    Session = get_session_factory()
    with Session() as session:
        acc1 = _account(session)
        _inbox(session, acc1, unread=5, total=10)
        acc2 = _account(session, sync_enabled=False, sync_status="auth_failed")
        acc3 = _account(session, sync_status="failed")  # enabled, no folders yet
        session.commit()

        result = query_global_inbox_stats(session)
        by_id = _by_id(result)
        # Disabled accounts are filtered by the aggregate itself; the
        # enabled-but-failed account stays listed with unknown counts.
        assert set(by_id) == {acc1.id, acc3.id}
        assert result.total_unread == 5
        assert by_id[acc1.id].unread_count == 5
        assert by_id[acc3.id].unread_count is None


@requires_db
def test_query_global_inbox_stats_normal_account_missing_folder_stats_propagates_null():
    Session = get_session_factory()
    with Session() as session:
        acc1 = _account(session)
        _inbox(session, acc1, unread=5, total=10)
        acc2 = _account(session)  # normal active, 0 inbox folders (sync in progress)
        session.commit()

        result = query_global_inbox_stats(session)
        by_id = _by_id(result)
        assert result.total_unread is None
        assert by_id[acc1.id].unread_count == 5
        assert by_id[acc2.id].unread_count is None


@requires_db
def test_query_group_inbox_stats_excludes_disabled_accounts():
    Session = get_session_factory()
    with Session() as session:
        group = AccountGroup(name=f"stats-group-{uuid.uuid4().hex[:8]}")
        session.add(group)
        session.flush()
        acc1 = _account(session, group_id=group.id)
        _inbox(session, acc1, unread=3, total=8)
        _account(session, sync_enabled=False, sync_status="auth_failed", group_id=group.id)
        session.commit()

        result = query_group_inbox_stats(session, group.id)
        by_id = _by_id(result)
        assert result.total_unread == 3
        assert set(by_id) == {acc1.id}
        assert by_id[acc1.id].unread_count == 3


# Replaces the complete-only aggregate fixture: nullable unread counters now require
# both complete and incomplete folder sets to be exercised by the read model.
@requires_db
def test_query_global_inbox_stats_keeps_unknown_folder_counters_unknown():
    Session = get_session_factory()
    with Session() as session:
        acc1 = _account(session)
        _inbox(session, acc1, unread=1, total=4)
        _inbox(session, acc1, unread=2, total=6)
        acc2 = _account(session)
        _inbox(session, acc2, unread=5, total=12)
        _inbox(session, acc2, unread=None, total=8)  # unread unknown for one folder
        session.commit()

        result = query_global_inbox_stats(session)
        by_id = _by_id(result)
        assert result.total_unread is None
        assert by_id[acc1.id].unread_count == 3
        assert by_id[acc1.id].total_count == 10
        assert by_id[acc2.id].unread_count is None
        assert by_id[acc2.id].total_count == 20


def test_api_mail_stats_endpoint():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    acc_id = uuid.uuid4()
    mock_out = GlobalStatsOut(
        total_unread=4,
        accounts=[
            {"account_id": acc_id, "unread_count": 4, "total_count": 12},
        ],
    )
    mock_session_factory = MagicMock()
    with patch("mail_core.api.mail.get_session_factory", return_value=mock_session_factory):
        with patch("mail_core.api.mail.query_global_inbox_stats", return_value=mock_out):
            resp = client.get("/api/mail/stats")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_unread"] == 4
            assert len(data["accounts"]) == 1
            assert data["accounts"][0]["account_id"] == str(acc_id)
            assert data["accounts"][0]["unread_count"] == 4
            assert data["accounts"][0]["total_count"] == 12
