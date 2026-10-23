from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from mail_core.api.app import app
from tests.mail_core.conftest import TEST_API_KEY
from mail_core.mail.application.queries import GlobalStatsOut, query_global_inbox_stats, query_group_inbox_stats
from mail_core.mail.storage.models import AccountGroup


def test_query_global_inbox_stats_excludes_faulty_zero_folder_account():
    session = MagicMock()
    acc1, acc2, acc3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # acc1: normal active, 1 inbox folder, unread=5
    # acc2: faulty, disabled & auth_failed, 0 inbox folders
    # acc3: faulty, enabled but sync_status='failed', 0 inbox folders
    session.execute.return_value.all.return_value = [
        (acc1, 1, 1, 5, 10, 1, True, "idle"),
        (acc2, 0, 0, None, None, 0, False, "auth_failed"),
        (acc3, 0, 0, None, None, 0, True, "failed"),
    ]
    result = query_global_inbox_stats(session)
    assert result.total_unread == 5
    assert result.accounts[0].unread_count == 5
    assert result.accounts[1].unread_count is None
    assert result.accounts[2].unread_count is None


def test_query_global_inbox_stats_normal_account_missing_folder_stats_propagates_null():
    session = MagicMock()
    acc1, acc2 = uuid.uuid4(), uuid.uuid4()
    # acc1: normal active, unread=5
    # acc2: normal active, but 0 inbox folders (sync in progress)
    session.execute.return_value.all.return_value = [
        (acc1, 1, 1, 5, 10, 1, True, "idle"),
        (acc2, 0, 0, None, None, 0, True, "idle"),
    ]
    result = query_global_inbox_stats(session)
    assert result.total_unread is None
    assert result.accounts[0].unread_count == 5
    assert result.accounts[1].unread_count is None


def test_query_group_inbox_stats_excludes_faulty_zero_folder_account():
    session = MagicMock()
    group_id = uuid.uuid4()
    session.get.return_value = MagicMock(spec=AccountGroup)
    acc1, acc2 = uuid.uuid4(), uuid.uuid4()
    session.execute.return_value.all.return_value = [
        (acc1, 1, 1, 3, 8, 1, True, "idle"),
        (acc2, 0, 0, None, None, 0, False, "auth_failed"),
    ]
    result = query_group_inbox_stats(session, group_id)
    assert result.total_unread == 3
    assert result.accounts[0].unread_count == 3
    assert result.accounts[1].unread_count is None


# Replaces the complete-only aggregate fixture: nullable unread counters now require
# both complete and incomplete folder sets to be exercised by the read model.
def test_query_global_inbox_stats_keeps_unknown_folder_counters_unknown():
    session = MagicMock()
    acc1, acc2 = uuid.uuid4(), uuid.uuid4()
    session.execute.return_value.all.return_value = [
        (acc1, 2, 2, 3, 10, 2),
        (acc2, 2, 2, 5, 20, 1),
    ]
    result = query_global_inbox_stats(session)
    assert result.total_unread is None
    assert result.accounts[0].unread_count == 3
    assert result.accounts[0].total_count == 10
    assert result.accounts[1].unread_count is None
    assert result.accounts[1].total_count == 20


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
