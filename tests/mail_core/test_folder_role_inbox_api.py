from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from mail_core.accounts import create_account
from mail_core.api.app import app
from tests.mail_core.conftest import TEST_API_KEY
from mail_core.db.session import get_session_factory
from mail_core.mail.storage import Folder, Message, MessageLocation

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_unified_inbox_folder_role_sent_and_default():
    Session = get_session_factory()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    base_time = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)

    with Session() as session:
        acc1 = create_account(session, email=f"role1-{uuid.uuid4().hex[:8]}@ex.com", provider="imap")
        acc2 = create_account(session, email=f"role2-{uuid.uuid4().hex[:8]}@ex.com", provider="imap")

        # acc1 folders
        f1_inbox = Folder(account_id=acc1.id, remote_id="INBOX", name="INBOX", role="inbox")
        f1_sent = Folder(account_id=acc1.id, remote_id="Sent", name="Sent Items", role="sent")
        # acc2 folders
        f2_sent = Folder(account_id=acc2.id, remote_id="Sent", name="已发送", role="sent")

        session.add_all([f1_inbox, f1_sent, f2_sent])
        session.flush()

        # Messages
        m_inbox = Message(
            account_id=acc1.id,
            remote_id="inbox-1",
            subject="Inbox Mail",
            from_address="sender@ex.com",
            sort_time=base_time,
            is_read=False,
            is_flagged=False,
            has_attachments=False,
        )
        m_sent1 = Message(
            account_id=acc1.id,
            remote_id="sent-1",
            subject="Sent Mail 1",
            from_address=acc1.email,
            sort_time=base_time + timedelta(minutes=1),
            is_read=True,
            is_flagged=False,
            has_attachments=False,
        )
        m_sent2 = Message(
            account_id=acc2.id,
            remote_id="sent-2",
            subject="Sent Mail 2",
            from_address=acc2.email,
            sort_time=base_time + timedelta(minutes=2),
            is_read=True,
            is_flagged=False,
            has_attachments=False,
        )
        session.add_all([m_inbox, m_sent1, m_sent2])
        session.flush()

        session.add(MessageLocation(message_id=m_inbox.id, folder_id=f1_inbox.id, uid=1))
        session.add(MessageLocation(message_id=m_sent1.id, folder_id=f1_sent.id, uid=2))
        session.add(MessageLocation(message_id=m_sent2.id, folder_id=f2_sent.id, uid=3))
        session.commit()

        acc1_id = acc1.id
        acc2_id = acc2.id
        m_inbox_id = str(m_inbox.id)
        m_sent1_id = str(m_sent1.id)
        m_sent2_id = str(m_sent2.id)

    # 1. Default without folder_role should return inbox messages
    res_default = client.get("/api/mail/inbox", params={"account_id": str(acc1_id)})
    assert res_default.status_code == 200
    ids_default = [item["id"] for item in res_default.json()["items"]]
    assert m_inbox_id in ids_default
    assert m_sent1_id not in ids_default

    # 2. folder_role=sent should return sent messages across accounts
    res_sent = client.get("/api/mail/inbox", params={"folder_role": "sent", "limit": 100})
    assert res_sent.status_code == 200
    ids_sent = [item["id"] for item in res_sent.json()["items"]]
    assert m_inbox_id not in ids_sent
    assert m_sent1_id in ids_sent
    assert m_sent2_id in ids_sent

    # 3. folder_role=sent with account_id should filter by account
    res_acc1_sent = client.get(
        "/api/mail/inbox",
        params={"folder_role": "sent", "account_id": str(acc1_id)},
    )
    assert res_acc1_sent.status_code == 200
    ids_acc1_sent = [item["id"] for item in res_acc1_sent.json()["items"]]
    assert ids_acc1_sent == [m_sent1_id]
