"""Test on-demand message body sync and archive priority governance (t034 AC-001 ~ AC-005)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import ArchiveState, JobStatus, JobType
from mail_core.mail.storage.models import Account, Message, MessageArchiveState, MessageBody, WorkerJob
from tests.mail_core.conftest import TEST_API_KEY

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_unarchived_message() -> tuple[uuid.UUID, uuid.UUID]:
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            email=f"ondemand-{uuid.uuid4().hex[:8]}@ex.com",
            provider="stub",
            credential_ref=f"ref-{uuid.uuid4().hex[:6]}",
        )
        session.add(acc)
        session.flush()

        msg = Message(
            account_id=acc.id,
            remote_id=f"remote-{uuid.uuid4().hex[:8]}",
            subject="Test On Demand Subject",
            from_address="sender@ex.com",
            from_name="Sender",
            to_addresses=["user@ex.com"],
            cc_addresses=[],
            sort_time=datetime(2018, 10, 26, 12, 0, 0, tzinfo=timezone.utc),
            is_read=False,
            has_attachments=False,
            snippet="Historical snippet",
        )
        session.add(msg)
        session.flush()

        st = MessageArchiveState(
            message_id=msg.id,
            state=ArchiveState.METADATA_SYNCED.value,
            priority=2,  # P2 older email
            retry_count=0,
        )
        session.add(st)
        session.commit()
        return acc.id, msg.id


def test_ac001_get_message_unarchived_escalates_priority_and_enqueues_job():
    acc_id, mid = _seed_unarchived_message()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    resp = client.get(f"/api/mail/messages/{mid}")
    assert resp.status_code == 200
    data = resp.json()
    assert not data["body"]
    assert data["parse_error"] is None

    Session = get_session_factory()
    with Session() as session:
        st = session.get(MessageArchiveState, mid)
        assert st is not None
        assert st.priority <= 0, "priority should be escalated to highest priority (<= 0)"

        job = session.scalars(
            select(WorkerJob)
            .where(
                WorkerJob.job_type == JobType.ARCHIVE_MIME_BATCH.value,
                WorkerJob.account_id == acc_id,
            )
            .order_by(WorkerJob.created_at.desc())
        ).first()
        assert job is not None
        assert job.priority == 10, "on-demand archive job priority should be 10"


def test_ac002_post_sync_body_completes_archive_and_returns_body():
    acc_id, mid = _seed_unarchived_message()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    sample_mime = (
        b"From: sender@ex.com\r\n"
        b"To: user@ex.com\r\n"
        b"Subject: Test On Demand Subject\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n\r\n"
        b"<div><p>Instant full body rendered successfully!</p></div>"
    )

    mock_provider = MagicMock()
    mock_provider.fetch_mime.return_value = sample_mime

    with patch("mail_core.blobs.archive.build_provider", return_value=mock_provider):
        resp = client.post(f"/api/mail/messages/{mid}/sync-body")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(mid)
        assert data["body"] is not None
        assert "Instant full body rendered successfully!" in data["body"]
        assert data["parse_error"] is None

    Session = get_session_factory()
    with Session() as session:
        st = session.get(MessageArchiveState, mid)
        assert st.state == ArchiveState.ARCHIVE_COMPLETE.value
        body = session.get(MessageBody, mid)
        assert body is not None
        assert "Instant full body rendered successfully!" in (body.text_html or "")


def test_ac003_worker_jobs_priority_governance():
    from mail_core.sync.delta import sync_folder_delta
    from mail_core.blobs.archive import run_archive_batch

    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            email=f"priority-{uuid.uuid4().hex[:8]}@ex.com",
            provider="stub",
            credential_ref="stub",
        )
        session.add(acc)
        session.flush()

        from mail_core.mail.storage.models import Folder, SyncCheckpoint
        folder = Folder(
            account_id=acc.id,
            remote_id="INBOX",
            name="INBOX",
            role="inbox",
        )
        session.add(folder)
        session.flush()

        cp = SyncCheckpoint(
            account_id=acc.id,
            folder_id=folder.id,
            full_scan_complete=True,
            uidvalidity=12345,
            cursor={"max_uid": 10},
        )
        session.add(cp)
        session.commit()
        fid = folder.id
        aid = acc.id

    # 验证 delta 轮询任务入队的优先级与去重键
    from mail_core.providers.base import DeltaPage
    mock_prov = MagicMock()
    mock_prov.delta_changes.return_value = DeltaPage(
        changes=[],
        next_cursor={"max_uid": 10},
        exhausted=True,
    )
    with patch("mail_core.sync.delta.build_provider", return_value=mock_prov):
        res = sync_folder_delta(account_id=aid, folder_id=fid, worker_id="test-worker")
        assert res["status"] == "ok"

    with Session() as session:
        delta_job = session.scalars(
            select(WorkerJob)
            .where(
                WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
                WorkerJob.account_id == aid,
                WorkerJob.status == JobStatus.PENDING.value,
            )
        ).first()
        assert delta_job is not None
        assert delta_job.priority == 75, "routine delta polling priority should be 75"
        assert delta_job.dedupe_key == f"delta:{aid}:{fid}", "delta polling should have dedupe_key"


def test_ac005_sync_body_captures_provider_or_parse_error():
    acc_id, mid = _seed_unarchived_message()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    mock_provider = MagicMock()
    mock_provider.fetch_mime.side_effect = RuntimeError("Remote IMAP server timeout (simulated)")

    with patch("mail_core.blobs.archive.build_provider", return_value=mock_provider):
        resp = client.post(f"/api/mail/messages/{mid}/sync-body")
        # 即使远端拉取失败，接口也应优雅返回并透传 parse_error
        assert resp.status_code == 200
        data = resp.json()
        assert data["parse_error"] is not None
        assert "Remote IMAP server timeout" in data["parse_error"]

    Session = get_session_factory()
    with Session() as session:
        body = session.get(MessageBody, mid)
        assert body is not None
        assert body.parse_error is not None
