"""POST /messages/{id}/read and /flag enqueue remote_operations."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobType, RemoteOperationStatus
from mail_core.mail.storage.models import Account, Folder, Message, MessageLocation, RemoteOperation, WorkerJob

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed() -> uuid.UUID:
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
            remote_id="rid-1",
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


def test_mark_read_and_flag_enqueue_ops():
    mid = _seed()
    client = TestClient(app)
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
