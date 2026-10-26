"""Tests for Gmail sync strategy, IMAP timeout, and transient error resilience (t056)."""

from __future__ import annotations

import inspect
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobType
from mail_core.mail.storage.models import Account, Folder, SyncStatus, WorkerJob
from mail_core.providers.base import RemoteFolder
from mail_core.providers.http import PermanentAuthError
from mail_core.providers.imap import ImapProvider
from mail_core.sync.engine import sync_account_folders, sync_folder_metadata
from mail_core.sync.jobs import JobStatus, enqueue_job
from mail_core.worker.handlers import handle_job


def test_imap_discover_folders_recognizes_all_and_flagged_roles(monkeypatch):
    """AC-002: \\All maps to 'all', \\Flagged maps to 'flagged'."""
    class FakeGmailIMAP:
        def list(self):
            return "OK", [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\HasChildren \\Noselect) "/" "[Gmail]"',
                b'(\\HasNoChildren \\All) "/" "[Gmail]/All Mail"',
                b'(\\HasNoChildren \\Flagged) "/" "[Gmail]/Starred"',
                b'(\\HasNoChildren \\Sent) "/" "[Gmail]/Sent Mail"',
                b'(\\HasNoChildren \\Drafts) "/" "[Gmail]/Drafts"',
                b'(\\HasNoChildren \\Trash) "/" "[Gmail]/Trash"',
                b'(\\HasNoChildren \\Junk) "/" "[Gmail]/Spam"',
            ]

        def logout(self):
            return "OK", []

    prov = ImapProvider("imap.gmail.com", 993, "alice@gmail.com", "pass", use_ssl=False)
    monkeypatch.setattr(prov, "_connect", lambda: FakeGmailIMAP())

    folders = prov.list_folder_catalog()
    by_remote = {f.remote_id: f for f in folders}

    assert by_remote["[Gmail]/All Mail"].role == "all"
    assert by_remote["[Gmail]/Starred"].role == "flagged"
    assert by_remote["[Gmail]/Sent Mail"].role == "sent"


def test_imap_provider_default_timeout_is_60s():
    """AC-003: ImapProvider default socket timeout is relaxed to 60.0s."""
    prov = ImapProvider("imap.example.com", 993, "u", "p", use_ssl=False)
    assert prov.timeout == 60.0


def test_sync_folder_metadata_default_max_pages_is_10():
    """AC-004: sync_folder_metadata default max_pages is 10."""
    sig = inspect.signature(sync_folder_metadata)
    assert sig.parameters["max_pages"].default == 10


def test_sync_account_folders_pauses_gmail_virtual_folders():
    """AC-001: For Gmail accounts, All Mail and Important folders default to paused and are not enqueued."""
    Session = get_session_factory()
    with Session() as session:
        account = Account(
            email=f"test_user_{uuid.uuid4().hex[:8]}@gmail.com",
            provider="imap",
            sync_enabled=True,
            sync_status="idle",
            config={"imap_host": "imap.gmail.com", "imap_port": 993},
        )
        session.add(account)
        session.commit()
        account_id = account.id

    fake_remote_folders = [
        RemoteFolder("INBOX", "INBOX", role="inbox", selectable=True),
        RemoteFolder("[Gmail]", "[Gmail]", role="other", selectable=False),
        RemoteFolder("[Gmail]/&YkBnCZCuTvY-", "[Gmail]/所有邮件", role="all", selectable=True),
        RemoteFolder("[Gmail]/&kc2JgQ-", "[Gmail]/重要", role="important", selectable=True),
        RemoteFolder("[Gmail]/&XfJT0ZCuTvY-", "[Gmail]/已发邮件", role="sent", selectable=True),
    ]

    mock_provider = MagicMock()
    mock_provider.list_folder_catalog.return_value = fake_remote_folders

    with patch("mail_core.sync.engine.build_provider", return_value=mock_provider):
        res = sync_account_folders(account_id, worker_id="test-worker")

    assert res["status"] == "ok"
    assert res["folders"] == 5

    with Session() as session:
        folders = session.query(Folder).filter_by(account_id=account_id).all()
        folder_map = {f.name: f for f in folders}

        assert folder_map["INBOX"].sync_status == SyncStatus.IDLE.value
        assert folder_map["[Gmail]/已发邮件"].sync_status == SyncStatus.IDLE.value
        assert folder_map["[Gmail]"].sync_status == SyncStatus.PAUSED.value
        assert folder_map["[Gmail]/所有邮件"].sync_status == SyncStatus.PAUSED.value
        assert folder_map["[Gmail]/重要"].sync_status == SyncStatus.PAUSED.value

        jobs = session.query(WorkerJob).filter_by(account_id=account_id).all()
        enqueued_folder_ids = [str(j.payload.get("folder_id")) for j in jobs]

        # INBOX and Sent should be enqueued
        assert str(folder_map["INBOX"].id) in enqueued_folder_ids
        assert str(folder_map["[Gmail]/已发邮件"].id) in enqueued_folder_ids
        # Virtual folders must NOT be enqueued for metadata sync
        assert str(folder_map["[Gmail]/所有邮件"].id) not in enqueued_folder_ids
        assert str(folder_map["[Gmail]/重要"].id) not in enqueued_folder_ids


def test_worker_transient_network_timeout_does_not_fail_account():
    """AC-005: Transient network timeout keeps account status intact and requeues job."""
    Session = get_session_factory()
    with Session() as session:
        account = Account(
            email=f"transient_{uuid.uuid4().hex[:8]}@gmail.com",
            provider="imap",
            sync_enabled=True,
            sync_status="running",
        )
        session.add(account)
        session.flush()

        job = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_METADATA.value,
            account_id=account.id,
            payload={"folder_id": str(uuid.uuid4())},
            priority=50,
        )
        job.status = JobStatus.CLAIMED.value
        job.locked_by = "test-worker"
        job.locked_at = datetime.now(timezone.utc)
        session.commit()
        account_id = account.id
        job_id = job.id

    with Session() as session:
        job = session.get(WorkerJob, job_id)
        with patch("mail_core.sync.engine.sync_folder_metadata", side_effect=TimeoutError("The read operation timed out")):
            res = handle_job(session, job, worker_id="test-worker")
        session.commit()

    assert res is False

    with Session() as session:
        account = session.get(Account, account_id)
        job = session.get(WorkerJob, job_id)

        # Job is requeued with backoff
        assert job.status == JobStatus.PENDING.value
        assert job.failure_attempts == 1
        # Account is NOT marked as failed!
        assert account.sync_status != SyncStatus.FAILED.value
        assert account.sync_status == "running"


def test_worker_permanent_auth_error_still_fails_and_disables_account():
    """PermanentAuthError must still set account to AUTH_FAILED and disable sync."""
    Session = get_session_factory()
    with Session() as session:
        account = Account(
            email=f"auth_fail_{uuid.uuid4().hex[:8]}@gmail.com",
            provider="imap",
            sync_enabled=True,
            sync_status="running",
        )
        session.add(account)
        session.flush()

        job = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_METADATA.value,
            account_id=account.id,
            payload={"folder_id": str(uuid.uuid4())},
            priority=50,
        )
        job.status = JobStatus.CLAIMED.value
        job.locked_by = "test-worker"
        job.locked_at = datetime.now(timezone.utc)
        session.commit()
        account_id = account.id
        job_id = job.id

    with Session() as session:
        job = session.get(WorkerJob, job_id)
        with patch("mail_core.sync.engine.sync_folder_metadata", side_effect=PermanentAuthError("Bad credentials")):
            res = handle_job(session, job, worker_id="test-worker")
        session.commit()

    assert res is False

    with Session() as session:
        account = session.get(Account, account_id)
        assert account.sync_status == SyncStatus.AUTH_FAILED.value
        assert account.sync_enabled is False
