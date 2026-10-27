"""Unit tests for synchronization mode policy: routine sync is delta, new account is full baseline."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobType, SyncStatus
from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint, SyncRequest, WorkerJob
from tests.mail_core.conftest import TEST_API_KEY

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_account_with_inbox() -> tuple[uuid.UUID, uuid.UUID]:
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            id=uuid.uuid4(),
            email=f"mode-policy-{uuid.uuid4().hex[:6]}@example.com",
            provider="stub",
            credential_ref=f"ref-{uuid.uuid4().hex[:6]}",
            sync_enabled=True,
        )
        session.add(acc)
        session.flush()

        folder = Folder(
            id=uuid.uuid4(),
            account_id=acc.id,
            remote_id="remote-inbox",
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
            cursor={"modseq": 10},
        )
        session.add(cp)
        session.commit()
        return acc.id, folder.id


def test_sync_all_accounts_enqueues_delta_mode():
    acc_id, folder_id = _seed_account_with_inbox()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    resp = client.post("/api/accounts/sync-all")
    assert resp.status_code == 202
    data = resp.json()
    req_id = uuid.UUID(data["id"])

    Session = get_session_factory()
    with Session() as session:
        req = session.get(SyncRequest, req_id)
        assert req is not None
        assert req.mode == "delta", "sync-all must use delta mode for routine sync"

        # Assert SYNC_ACCOUNT_FOLDERS was enqueued as the root discovery job
        discovery_job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == acc_id,
                WorkerJob.job_type == JobType.SYNC_ACCOUNT_FOLDERS.value,
                WorkerJob.dedupe_key == f"sync:{acc_id}",
            )
        )
        assert discovery_job is not None

    # Simulate running discovery job: because checkpoint is already complete,
    # it must spawn SYNC_FOLDER_DELTA, never a heavy metadata full-scan
    from unittest.mock import MagicMock, patch
    from mail_core.providers.base import RemoteFolder
    from mail_core.sync.engine import sync_account_folders

    remote_inbox = RemoteFolder(remote_id="remote-inbox", name="Inbox", role="inbox", selectable=True)
    mock_provider = MagicMock()
    mock_provider.list_folders.return_value = [remote_inbox]
    mock_provider.list_folder_catalog.return_value = [remote_inbox]
    with patch("mail_core.sync.engine.build_provider", return_value=mock_provider):
        sync_account_folders(acc_id, worker_id="test-worker", full=False, request_id=req_id)

    with Session() as session:
        delta_job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == acc_id,
                WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
            )
        )
        assert delta_job is not None, "sync_account_folders in non-full mode must enqueue SYNC_FOLDER_DELTA for folders with existing baseline"
        meta_job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == acc_id,
                WorkerJob.job_type == JobType.SYNC_FOLDER_METADATA.value,
            )
        )
        assert meta_job is None, "sync_account_folders in non-full mode must NOT enqueue SYNC_FOLDER_METADATA for folders with existing baseline"


def test_sync_single_account_enqueues_delta_mode():
    acc_id, folder_id = _seed_account_with_inbox()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})

    resp = client.post(f"/api/accounts/{acc_id}/sync")
    assert resp.status_code == 202
    data = resp.json()
    req_id = uuid.UUID(data["id"])

    Session = get_session_factory()
    with Session() as session:
        req = session.get(SyncRequest, req_id)
        assert req is not None
        assert req.mode == "delta", "single account sync must use delta mode for routine sync"

    from unittest.mock import MagicMock, patch
    from mail_core.providers.base import RemoteFolder
    from mail_core.sync.engine import sync_account_folders

    remote_inbox = RemoteFolder(remote_id="remote-inbox", name="Inbox", role="inbox", selectable=True)
    mock_provider = MagicMock()
    mock_provider.list_folders.return_value = [remote_inbox]
    mock_provider.list_folder_catalog.return_value = [remote_inbox]
    with patch("mail_core.sync.engine.build_provider", return_value=mock_provider):
        sync_account_folders(acc_id, worker_id="test-worker", full=False, request_id=req_id)

    with Session() as session:
        delta_job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == acc_id,
                WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
            )
        )
        assert delta_job is not None
        meta_job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == acc_id,
                WorkerJob.job_type == JobType.SYNC_FOLDER_METADATA.value,
            )
        )
        assert meta_job is None


def test_new_account_without_checkpoint_enqueues_full_metadata_baseline():
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            id=uuid.uuid4(),
            email=f"new-acc-{uuid.uuid4().hex[:6]}@example.com",
            provider="stub",
            credential_ref=f"ref-{uuid.uuid4().hex[:6]}",
            sync_enabled=True,
        )
        session.add(acc)
        session.flush()

        folder = Folder(
            id=uuid.uuid4(),
            account_id=acc.id,
            remote_id="remote-new-inbox",
            name="Inbox",
            role="inbox",
            sync_status=SyncStatus.IDLE.value,
        )
        session.add(folder)
        session.commit()
        new_acc_id = acc.id

    from unittest.mock import MagicMock, patch
    from mail_core.providers.base import RemoteFolder
    from mail_core.sync.engine import sync_account_folders

    rf = RemoteFolder(remote_id="remote-new-inbox", name="Inbox", role="inbox", selectable=True)
    mock_provider = MagicMock()
    mock_provider.list_folders.return_value = [rf]
    mock_provider.list_folder_catalog.return_value = [rf]
    with patch("mail_core.sync.engine.build_provider", return_value=mock_provider):
        sync_account_folders(new_acc_id, worker_id="test-worker", full=False)

    with Session() as session:
        # Without checkpoint baseline, must spawn SYNC_FOLDER_METADATA to establish initial baseline
        meta_job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == new_acc_id,
                WorkerJob.job_type == JobType.SYNC_FOLDER_METADATA.value,
            )
        )
        assert meta_job is not None, "New account without baseline must enqueue SYNC_FOLDER_METADATA to establish baseline"
        delta_job = session.scalar(
            select(WorkerJob).where(
                WorkerJob.account_id == new_acc_id,
                WorkerJob.job_type == JobType.SYNC_FOLDER_DELTA.value,
            )
        )
        assert delta_job is None, "New account without baseline must NOT enqueue SYNC_FOLDER_DELTA"
