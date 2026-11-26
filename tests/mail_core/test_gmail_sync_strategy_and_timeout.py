"""Tests for Gmail sync strategy, IMAP timeout, and transient error resilience (t056)."""

from __future__ import annotations

import inspect
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobType
from mail_core.mail.storage.models import Account, Folder, WorkerJob
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



@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_worker_transient_network_timeout_does_not_fail_account():
    """AC-005: Transient network timeout keeps account status intact and requeues job."""
    Session = get_session_factory()
    with Session() as session:
        account = Account(
            email=f"transient_{uuid.uuid4().hex[:8]}@gmail.com",
            provider="imap",
            sync_enabled=True,
        )
        session.add(account)
        session.flush()

        job = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_METADATA.value,
            account_id=account.id,
            payload={"folder_id": str(uuid.uuid4())},
            priority=50,
            execution_origin="foreground",
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
        # t076: a foreground transport failure degrades connectivity but must
        # never invalidate the credential (AC-004 / AC-005).
        assert account.credential_state == "valid"
        assert account.connectivity_state == "degraded"
        assert account.sync_activity == "syncing"


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_worker_permanent_auth_error_still_fails_and_disables_account():
    """PermanentAuthError must still set account to AUTH_FAILED and disable sync."""
    Session = get_session_factory()
    with Session() as session:
        account = Account(
            email=f"auth_fail_{uuid.uuid4().hex[:8]}@gmail.com",
            provider="imap",
            sync_enabled=True,
        )
        session.add(account)
        session.flush()

        job = enqueue_job(
            session,
            job_type=JobType.SYNC_FOLDER_METADATA.value,
            account_id=account.id,
            payload={"folder_id": str(uuid.uuid4())},
            priority=50,
            execution_origin="foreground",
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
        assert account.credential_state == "invalid"
        assert account.sync_enabled is False
