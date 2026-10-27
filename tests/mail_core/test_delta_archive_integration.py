"""Integration tests for delta sync without self-scheduling and automatic body archive pipeline (t057 AC-003, AC-004, AC-005)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select

from mail_core.blobs.archive import run_archive_batch
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import ArchiveState, JobType, SyncStatus
from mail_core.mail.storage.models import Account, Folder, Message, MessageArchiveState, MessageBody, SyncCheckpoint, WorkerJob
from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta
from mail_core.sync.delta import sync_folder_delta

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_account_with_checkpoint(session) -> tuple[uuid.UUID, uuid.UUID]:
    acc = Account(
        id=uuid.uuid4(),
        email=f"delta-{uuid.uuid4().hex[:6]}@example.com",
        provider="stub",
        credential_ref=f"ref-{uuid.uuid4().hex[:6]}",
        sync_enabled=True,
    )
    session.add(acc)
    session.flush()

    folder = Folder(
        id=uuid.uuid4(),
        account_id=acc.id,
        remote_id=f"remote-{uuid.uuid4().hex[:6]}",
        name="Inbox",
        role="inbox",
        sync_status=SyncStatus.IDLE.value,
    )
    session.add(folder)
    session.flush()

    cp = SyncCheckpoint(
        account_id=acc.id,
        folder_id=folder.id,
        full_scan_complete=True,
        cursor={"modseq": 1},
    )
    session.add(cp)
    session.commit()
    return acc.id, folder.id


def test_ac003_delta_exhausted_no_longer_self_schedules():
    Session = get_session_factory()
    with Session() as session:
        acc_id, folder_id = _seed_account_with_checkpoint(session)

    mock_provider = MagicMock()
    mock_provider.delta_changes.return_value = DeltaPage(
        changes=[],
        next_cursor={"modseq": 2},
        exhausted=True,
    )

    with patch("mail_core.sync.delta.build_provider", return_value=mock_provider):
        result = sync_folder_delta(
            acc_id,
            folder_id,
            worker_id="test-worker",
        )

    assert result["status"] == "ok"
    assert result["exhausted"] is True

    # Assert no successor delta job is self-scheduled into worker_jobs
    with Session() as session:
        followup_jobs = list(
            session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == acc_id,
                    WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
                )
            ).all()
        )
        assert len(followup_jobs) == 0, "sync_folder_delta must NOT self-schedule a successor delta job"


def test_ac004_and_ac005_delta_upsert_enqueues_archive_and_persists_body():
    Session = get_session_factory()
    with Session() as session:
        acc_id, folder_id = _seed_account_with_checkpoint(session)

    new_remote_id = f"msg-{uuid.uuid4().hex[:8]}"
    meta = RemoteMessageMeta(
        remote_id=new_remote_id,
        subject="Hello Automated Archive",
        from_address="sender@example.com",
        from_name="Sender",
        sort_time=datetime.now(timezone.utc),
        is_read=False,
        has_attachments=False,
        snippet="Snippet text",
    )
    mock_provider = MagicMock()
    mock_provider.delta_changes.return_value = DeltaPage(
        changes=[DeltaChange(kind="upsert", remote_id=new_remote_id, meta=meta)],
        next_cursor={"modseq": 2},
        exhausted=True,
    )
    raw_mime = (
        b"From: sender@example.com\r\n"
        b"To: delta@example.com\r\n"
        b"Subject: Hello Automated Archive\r\n"
        b"Content-Type: text/html; charset=utf-8\r\n"
        b"\r\n"
        b"<html><body><p>This is the full email body stored in database.</p></body></html>\r\n"
    )
    mock_provider.fetch_mime.return_value = raw_mime

    # Step 1: Run delta sync (AC-004)
    with patch("mail_core.sync.delta.build_provider", return_value=mock_provider):
        result = sync_folder_delta(
            acc_id,
            folder_id,
            worker_id="test-worker",
        )

    assert result["status"] == "ok"
    assert result["upserted"] == 1

    # Verify ARCHIVE_MIME_BATCH was enqueued
    with Session() as session:
        archive_job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == acc_id,
                WorkerJob.job_type == JobType.ARCHIVE_MIME_BATCH.value,
            )
        )
        assert archive_job is not None, "ARCHIVE_MIME_BATCH job must be enqueued automatically when upserted > 0"
        assert archive_job.dedupe_key == f"archive_mime_batch:{acc_id}"

        # Check message was created
        msg = session.scalar(
            select(Message).where(Message.account_id == acc_id, Message.remote_id == new_remote_id)
        )
        assert msg is not None
        mid = msg.id

    # Step 2: Run archive batch to simulate worker consuming the job (AC-005)
    with patch("mail_core.blobs.archive.build_provider", return_value=mock_provider):
        archive_result = run_archive_batch(
            account_id=acc_id,
            worker_id="test-worker",
        )
    assert archive_result["completed"] == 1

    # Verify message body is persisted into PostgreSQL message_bodies table
    with Session() as session:
        body = session.get(MessageBody, mid)
        assert body is not None, "MessageBody row must exist in PostgreSQL"
        assert body.text_html is not None
        assert "This is the full email body stored in database" in body.text_html
