"""POST /messages/{id}/read and /flag enqueue remote_operations."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.api.app import app
from tests.mail_core.conftest import TEST_API_KEY
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobType, RemoteOperationStatus
from mail_core.mail.storage.models import Account, AccountGroup, Folder, Message, MessageLocation, RemoteOperation, WorkerJob

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed(*, remote_id: str | None = "rid-1") -> uuid.UUID:
    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"mut-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        msg = Message(
            account_id=acc.id,
            remote_id=remote_id,
            subject="Hi",
            from_address="a@b.c",
            sort_time=datetime.now(timezone.utc),
            is_read=False,
            is_flagged=False,
        )
        session.add(msg)
        session.flush()
        session.add(MessageLocation(message_id=msg.id, folder_id=folder.id, uid=1))
        session.commit()
        return msg.id


def _seed_many(count: int, *, grouped: bool = False) -> tuple[uuid.UUID, list[uuid.UUID], uuid.UUID | None]:
    Session = get_session_factory()
    with Session() as session:
        group = None
        if grouped:
            group = AccountGroup(name=f"mut-batch-{uuid.uuid4().hex[:8]}")
            session.add(group)
            session.flush()
        acc = Account(
            email=f"mut-batch-{uuid.uuid4().hex[:8]}@ex.com",
            provider="memory",
            credential_ref="r",
            group_id=group.id if group is not None else None,
        )
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        message_ids = []
        for index in range(count):
            msg = Message(
                account_id=acc.id,
                remote_id=f"rid-batch-{index}",
                subject="Hi",
                from_address="a@b.c",
                sort_time=datetime.now(timezone.utc),
                is_read=False,
                is_flagged=False,
            )
            session.add(msg)
            session.flush()
            session.add(MessageLocation(message_id=msg.id, folder_id=folder.id, uid=index + 1))
            message_ids.append(msg.id)
        session.commit()
        return acc.id, message_ids, group.id if group is not None else None


def test_mark_read_and_flag_enqueue_ops():
    mid = _seed()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    r = client.post(f"/api/mail/messages/{mid}/read", json={"is_read": True})
    assert r.status_code == 200
    assert r.json()["is_read"] is True

    f = client.post(f"/api/mail/messages/{mid}/flag", json={"is_flagged": True})
    assert f.status_code == 200
    assert f.json()["is_flagged"] is True

    Session = get_session_factory()
    with Session() as session:
        msg = session.get(Message, mid)
        assert msg.is_read and msg.is_flagged
        ops = list(session.scalars(select(RemoteOperation).where(RemoteOperation.account_id == msg.account_id)))
        types = {o.op_type for o in ops}
        assert "mark_read" in types and "set_flag" in types
        assert all(o.status == RemoteOperationStatus.PENDING.value for o in ops)
        jobs = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == msg.account_id,
                    WorkerJob.job_type == JobType.REMOTE_OPERATION_PUSH.value,
                )
            )
        )
        assert len(jobs) >= 1

    missing = client.post(f"/api/mail/messages/{uuid.uuid4()}/read", json={"is_read": True})
    assert missing.status_code == 404


def test_mark_read_recomputes_all_locations_and_is_idempotent():
    from mail_core.mail.application.mutations import set_message_read
    from mail_core.mail.storage.models import FolderStats, OutboxEvent
    from unittest.mock import patch

    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"mut2-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
        session.add(acc)
        session.flush()
        f1 = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        f2 = Folder(account_id=acc.id, remote_id="Archive", name="Archive", role="archive")
        session.add_all([f1, f2])
        session.flush()
        msg = Message(
            account_id=acc.id,
            remote_id="rid-multi",
            subject="Hi",
            from_address="a@b.c",
            sort_time=datetime.now(timezone.utc),
            is_read=False,
            is_flagged=False,
        )
        session.add(msg)
        session.flush()
        session.add(MessageLocation(message_id=msg.id, folder_id=f1.id, uid=1))
        session.add(MessageLocation(message_id=msg.id, folder_id=f2.id, uid=2))
        session.commit()
        mid, fid1, fid2, aid = msg.id, f1.id, f2.id, acc.id

    with Session() as session:
        with patch("mail_core.mail.application.mutations.try_notify_outbox") as notify:
            r1 = set_message_read(session, mid, is_read=True)
            r2 = set_message_read(session, mid, is_read=True)  # same idempotency key
            session.commit()
            assert r1.operation_id == r2.operation_id
            notify.assert_called()

        stats1 = session.get(FolderStats, fid1)
        stats2 = session.get(FolderStats, fid2)
        assert stats1 is not None and stats2 is not None
        assert stats1.unread_count == 0
        assert stats2.unread_count == 0

        ops = list(session.scalars(select(RemoteOperation).where(RemoteOperation.account_id == aid)))
        assert sum(1 for o in ops if o.op_type == "mark_read") == 1

        folder_events = list(
            session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.account_id == aid,
                    OutboxEvent.event_type == "folder.stats_updated",
                )
            )
        )
        folder_ids = {e.payload.get("folder_id") for e in folder_events}
        assert str(fid1) in folder_ids and str(fid2) in folder_ids


def test_mark_all_read_api():
    mid = _seed()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    r = client.post("/api/mail/mark-all-read", json={"folder_role": "inbox"})
    assert r.status_code == 200
    res = r.json()
    assert res["success"] is True
    assert res["count"] >= 1
    assert res["scope_type"] == "global"
    assert res["scope_id"] is None

    r2 = client.post("/api/mail/mark-all-read", json={"folder_role": "inbox"})
    assert r2.status_code == 200
    assert r2.json()["count"] == 0

    Session = get_session_factory()
    with Session() as session:
        msg = session.get(Message, mid)
        assert msg.is_read is True


def test_mark_all_read_api_commits_bounded_batches(monkeypatch):
    from mail_core.api import mail as mail_api

    account_id, message_ids, _ = _seed_many(5)
    monkeypatch.setattr(mail_api, "MARK_ALL_READ_BATCH_SIZE", 2, raising=False)
    original = mail_api.mark_all_messages_read
    batch_counts = []
    batch_cursors = []
    batch_last_ids = []

    def track_batch(session, **kwargs):
        batch_cursors.append(kwargs.get("after_message_id"))
        batch = original(session, **kwargs)
        batch_counts.append(batch.count)
        if batch.last_message_id is not None:
            batch_last_ids.append(batch.last_message_id)
        return batch

    monkeypatch.setattr(mail_api, "mark_all_messages_read", track_batch)
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    response = client.post(
        "/api/mail/mark-all-read",
        json={"account_id": str(account_id), "folder_role": "inbox"},
    )

    assert response.status_code == 200
    assert response.json()["count"] == 5
    assert response.json()["scope_type"] == "account"
    assert response.json()["scope_id"] == str(account_id)
    assert batch_counts == [2, 2, 1]
    assert batch_cursors == [None, *batch_last_ids[:2]]

    Session = get_session_factory()
    with Session() as session:
        assert all(session.get(Message, message_id).is_read is True for message_id in message_ids)
        operations = list(session.scalars(select(RemoteOperation).where(RemoteOperation.account_id == account_id)))
        assert len(operations) == 5


def test_mark_all_read_api_keeps_committed_batches_retryable(monkeypatch):
    from mail_core.api import mail as mail_api

    account_id, message_ids, _ = _seed_many(5)
    monkeypatch.setattr(mail_api, "MARK_ALL_READ_BATCH_SIZE", 2, raising=False)
    original = mail_api.mark_all_messages_read
    calls = 0

    def fail_second_batch(session, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected second-batch failure")
        return original(session, **kwargs)

    monkeypatch.setattr(mail_api, "mark_all_messages_read", fail_second_batch)
    client = TestClient(
        app,
        headers={"Authorization": f"Bearer {TEST_API_KEY}"},
        raise_server_exceptions=False,
    )
    failed = client.post(
        "/api/mail/mark-all-read",
        json={"account_id": str(account_id), "folder_role": "inbox"},
    )

    assert failed.status_code == 500
    Session = get_session_factory()
    with Session() as session:
        states = [session.get(Message, message_id).is_read for message_id in message_ids]
        assert states.count(True) == 2
        assert states.count(False) == 3

    monkeypatch.setattr(mail_api, "mark_all_messages_read", original)
    retry = client.post(
        "/api/mail/mark-all-read",
        json={"account_id": str(account_id), "folder_role": "inbox"},
    )
    assert retry.status_code == 200
    assert retry.json()["count"] == 3
    with Session() as session:
        assert all(session.get(Message, message_id).is_read is True for message_id in message_ids)
        operations = list(session.scalars(select(RemoteOperation).where(RemoteOperation.account_id == account_id)))
        assert len(operations) == 5


def test_mark_all_read_api_freezes_group_members_across_batches(monkeypatch):
    from mail_core.api import mail as mail_api

    account_id, message_ids, group_id = _seed_many(5, grouped=True)
    assert group_id is not None
    monkeypatch.setattr(mail_api, "MARK_ALL_READ_BATCH_SIZE", 2, raising=False)
    original = mail_api.mark_all_messages_read
    batch_scopes = []

    def move_account_after_first_batch(session, **kwargs):
        batch_scopes.append(kwargs.get("account_ids"))
        batch = original(session, **kwargs)
        if len(batch_scopes) == 1:
            account = session.get(Account, account_id)
            assert account is not None
            account.group_id = None
            session.flush()
        return batch

    monkeypatch.setattr(mail_api, "mark_all_messages_read", move_account_after_first_batch)
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    response = client.post("/api/mail/mark-all-read", json={"group_id": str(group_id)})

    assert response.status_code == 200
    assert response.json()["count"] == 5
    assert response.json()["scope_type"] == "group"
    assert response.json()["scope_id"] == str(group_id)
    assert response.json()["account_id"] is None
    assert batch_scopes == [[account_id], [account_id], [account_id]]
    Session = get_session_factory()
    with Session() as session:
        assert all(session.get(Message, message_id).is_read is True for message_id in message_ids)


def test_local_only_messages_keep_read_flag_local_and_reject_trash():
    mid = _seed(remote_id=None)
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    read = client.post(f"/api/mail/messages/{mid}/read", json={"is_read": True})
    assert read.status_code == 200
    assert read.json()["operation_id"] is None

    flag = client.post(f"/api/mail/messages/{mid}/flag", json={"is_flagged": True})
    assert flag.status_code == 200
    assert flag.json()["operation_id"] is None

    mark_unread = client.post(f"/api/mail/messages/{mid}/read", json={"is_read": False})
    assert mark_unread.status_code == 200
    batch = client.post("/api/mail/mark-all-read", json={"folder_role": "inbox"})
    assert batch.status_code == 200
    assert batch.json()["count"] >= 1

    Session = get_session_factory()
    with Session() as session:
        message = session.get(Message, mid)
        assert message is not None and message.is_read is True and message.is_flagged is True
        assert session.scalars(select(RemoteOperation).where(RemoteOperation.account_id == message.account_id)).all() == []
        assert session.scalars(select(WorkerJob).where(WorkerJob.account_id == message.account_id)).all() == []

    trash = client.post(f"/api/mail/messages/{mid}/trash")
    assert trash.status_code == 409
    assert "provider remote id" in trash.json()["detail"]
    with Session() as session:
        assert session.get(Message, mid) is not None

