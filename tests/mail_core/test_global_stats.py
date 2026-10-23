from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from mail_core.api.app import app
from tests.mail_core.conftest import TEST_API_KEY
from mail_core.mail.application.queries import GlobalStatsOut, query_global_inbox_stats


def test_query_global_inbox_stats_calculation():
    session = MagicMock()
    acc1 = uuid.uuid4()
    acc2 = uuid.uuid4()
    session.execute.return_value.all.return_value = [
        (acc1, 1, 1, 3, 10),
        (acc2, 1, 1, 5, 20),
    ]
    res = query_global_inbox_stats(session)
    assert isinstance(res, GlobalStatsOut)
    assert res.total_unread == 8
    assert len(res.accounts) == 2
    assert res.accounts[0].account_id == acc1
    assert res.accounts[0].unread_count == 3
    assert res.accounts[0].total_count == 10
    assert res.accounts[1].account_id == acc2
    assert res.accounts[1].unread_count == 5
    assert res.accounts[1].total_count == 20


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
