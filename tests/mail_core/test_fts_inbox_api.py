from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.accounts import create_account
from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.storage import Folder, FolderStats, Message, MessageLocation, MessageSearch
from mail_core.search.index import upsert_message_search
from mail_core.threading.rules import assign_thread_for_message, normalize_subject

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_unified_inbox_folder_stats_search_and_thread():
    Session = get_session_factory()
    client = TestClient(app)
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc = create_account(session, email=f"api-{uuid.uuid4().hex[:8]}@ex.com", provider="imap")
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        m1 = Message(
            account_id=acc.id,
            remote_id="1",
            subject="Hello Project Phoenix",
            from_address="alice@ex.com",
            from_name="Alice",
            sort_time=now,
            is_read=False,
            snippet="discuss phoenix roadmap",
            internet_message_id="<m1@ex.com>",
        )
        session.add(m1)
        session.flush()
        session.add(MessageLocation(message_id=m1.id, folder_id=folder.id, uid=1))
        session.add(FolderStats(folder_id=folder.id, total_count=1, unread_count=1))
        upsert_message_search(session, message_id=m1.id, body_text="discuss phoenix roadmap")
        assign_thread_for_message(session, message=m1)
        session.commit()
        account_id = acc.id
        folder_id = folder.id
        message_id = m1.id

    inbox = client.get("/api/mail/inbox", params={"account_id": str(account_id)})
    assert inbox.status_code == 200
    body = inbox.json()
    assert any(i["id"] == str(message_id) for i in body["items"])

    stats = client.get(f"/api/mail/accounts/{account_id}/folder-stats")
    assert stats.status_code == 200
    assert stats.json()["folders"][0]["unread_count"] == 1

    one = client.get(f"/api/mail/folders/{folder_id}/stats")
    assert one.status_code == 200
    assert one.json()["total_count"] == 1

    search = client.get("/api/mail/search", params={"q": "phoenix", "account_id": str(account_id)})
    assert search.status_code == 200
    assert str(message_id) in search.json()["message_ids"]

    assert normalize_subject("Re: Hello") == "hello"
    with Session() as session:
        msg = session.get(Message, message_id)
        assert msg.thread_id is not None
        row = session.get(MessageSearch, message_id)
        assert row is not None
        assert "Phoenix" in row.subject
