"""GET /api/mail/messages/{id} (+ /body) — minimal reader endpoints."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.api.app import app
from tests.mail_core.conftest import TEST_API_KEY
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import ArchiveState, JobType
from mail_core.mail.application.queries import get_message_detail
from mail_core.mail.storage.models import Account, Attachment, Message, MessageArchiveState, MessageBody, WorkerJob

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_message(*, html: str | None = "<p>hi</p>", plain: str | None = "hi") -> uuid.UUID:
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            email=f"reader-{uuid.uuid4().hex[:8]}@ex.com",
            provider="stub",
            credential_ref="r",
        )
        session.add(acc)
        session.flush()
        msg = Message(
            account_id=acc.id,
            remote_id=f"r-{uuid.uuid4().hex[:8]}",
            subject="Hello",
            from_address="a@b.c",
            from_name="Ann",
            to_addresses=["you@ex.com"],
            cc_addresses=[],
            sort_time=datetime.now(timezone.utc),
            is_read=False,
            has_attachments=True,
            snippet="hi",
        )
        session.add(msg)
        session.flush()
        session.add(
            MessageBody(
                message_id=msg.id,
                text_html=html,
                text_plain=plain,
            )
        )
        session.add(
            Attachment(
                message_id=msg.id,
                filename="note.txt",
                content_type="text/plain",
                size_bytes=3,
            )
        )
        session.commit()
        return msg.id


def test_get_message_detail_query_and_api():
    mid = _seed_message()
    Session = get_session_factory()
    with Session() as session:
        detail = get_message_detail(session, mid)
        assert detail.body_type == "html"
        assert detail.body_html and "hi" in detail.body_html
        assert len(detail.attachments) == 1

    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    r = client.get(f"/api/mail/messages/{mid}")
    assert r.status_code == 200
    data = r.json()
    assert data["subject"] == "Hello"
    assert data["body_type"] == "html"
    assert "hi" in data["body"]
    assert data["attachments"][0]["name"] == "note.txt"

    assert data["from"] and data["is_flagged"] is False
    # Body-only duplicate endpoint is gone; GET /messages/{id} is the reader source.
    assert client.get(f"/api/mail/messages/{mid}/body").status_code == 404
    # read/flag require an explicit body (no implicit True).
    assert client.post(f"/api/mail/messages/{mid}/read").status_code == 422
    assert client.post(f"/api/mail/messages/{mid}/flag", json={}).status_code == 422

    missing = client.get(f"/api/mail/messages/{uuid.uuid4()}")
    assert missing.status_code == 404


def test_get_message_plain_only():
    mid = _seed_message(html=None, plain="plain body")
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    data = client.get(f"/api/mail/messages/{mid}").json()
    assert data["body_type"] == "text"
    assert data["body"] == "plain body"


def test_missing_archive_state_stays_unknown_in_detail_and_sync_body():
    Session = get_session_factory()
    with Session() as session:
        account = Account(
            email=f"legacy-unknown-{uuid.uuid4().hex[:8]}@ex.com",
            provider="stub",
            credential_ref="legacy-unknown",
        )
        session.add(account)
        session.flush()
        message = Message(
            account_id=account.id,
            remote_id=f"legacy-{uuid.uuid4().hex}",
            subject="Legacy message",
            from_address="sender@example.com",
            sort_time=None,
        )
        session.add(message)
        session.flush()
        session.add(MessageBody(message_id=message.id, text_plain="", text_html=None))
        session.commit()
        message_id, account_id = message.id, account.id

    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    with patch("mail_core.blobs.archive.build_provider") as build_provider:
        detail = client.get(f"/api/mail/messages/{message_id}")
        assert detail.status_code == 200
        assert detail.json()["is_archived"] is None

        sync_body = client.post(f"/api/mail/messages/{message_id}/sync-body")
        assert sync_body.status_code == 200
        assert sync_body.json()["is_archived"] is None
        build_provider.assert_not_called()

    with Session() as session:
        assert session.get(MessageArchiveState, message_id) is None
        assert session.scalars(
            select(WorkerJob).where(
                WorkerJob.account_id == account_id,
                WorkerJob.job_type == JobType.ARCHIVE_MIME_BATCH.value,
            )
        ).all() == []


def test_sync_body_refuses_message_without_provider_remote_id():
    Session = get_session_factory()
    with Session() as session:
        account = Account(
            email=f"legacy-unaddressable-{uuid.uuid4().hex[:8]}@ex.com",
            provider="imap",
            credential_ref="legacy-unaddressable",
        )
        session.add(account)
        session.flush()
        message = Message(
            account_id=account.id,
            remote_id=None,
            subject="Legacy local-only message",
            from_address="sender@example.com",
            sort_time=None,
        )
        session.add(message)
        session.flush()
        session.add(MessageBody(message_id=message.id, text_plain="cached local body", text_html=None))
        session.commit()
        message_id = message.id

    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    with patch("mail_core.blobs.archive.run_archive_batch") as run_archive:
        response = client.post(f"/api/mail/messages/{message_id}/sync-body")
    assert response.status_code == 409
    assert "provider remote id" in response.json()["detail"]
    run_archive.assert_not_called()


def test_detail_does_not_schedule_archive_for_message_without_provider_remote_id():
    Session = get_session_factory()
    with Session() as session:
        account = Account(
            email=f"legacy-unaddressable-detail-{uuid.uuid4().hex[:8]}@ex.com",
            provider="imap",
            credential_ref="legacy-unaddressable-detail",
        )
        session.add(account)
        session.flush()
        message = Message(
            account_id=account.id,
            remote_id=None,
            subject="Legacy local-only message",
            from_address="sender@example.com",
            sort_time=None,
        )
        session.add(message)
        session.flush()
        archive_state = MessageArchiveState(
            message_id=message.id,
            state=ArchiveState.METADATA_SYNCED.value,
            priority=3,
        )
        session.add_all((archive_state, MessageBody(message_id=message.id, text_plain="", text_html=None)))
        session.commit()
        message_id, account_id = message.id, account.id

    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    detail = client.get(f"/api/mail/messages/{message_id}")
    assert detail.status_code == 200
    assert detail.json()["is_archived"] is False

    with Session() as session:
        state = session.get(MessageArchiveState, message_id)
        assert state is not None and state.priority == 3
        jobs = session.scalars(
            select(WorkerJob).where(
                WorkerJob.account_id == account_id,
                WorkerJob.job_type == JobType.ARCHIVE_MIME_BATCH.value,
            )
        ).all()
        assert jobs == []
