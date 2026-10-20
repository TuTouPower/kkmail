"""IMAP sync via Worker engines — live pymap when available, else MemoryProvider."""

from __future__ import annotations

import os
import socket
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, func

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import JobType, ProviderType
from mail_core.mail.storage import Folder, Message, WorkerJob
from mail_core.providers.base import RemoteFolder, RemoteMessageMeta
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.sync import enqueue_job, sync_account_folders, sync_folder_metadata
from mail_core.sync.jobs import claim_jobs
from mail_core.worker.handlers import handle_job

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _imap_up() -> bool:
    host = os.environ.get("MAIL_CORE_IMAP_HOST", "127.0.0.1")
    port = int(os.environ.get("MAIL_CORE_IMAP_PORT", "1143"))
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def test_memory_provider_sync_folders_and_metadata():
    store = DictCredentialStore({"mem:x": "unused"})
    set_credential_store(store)
    Session = get_session_factory()
    provider = MemoryProvider(
        folders=[RemoteFolder("INBOX", "INBOX", "inbox")],
        page_size=2,
    )
    now = datetime.now(timezone.utc)
    provider.seed(
        "INBOX",
        [
            RemoteMessageMeta(
                remote_id=str(i),
                subject=f"S{i}",
                from_address="a@b.c",
                from_name="A",
                sort_time=now,
                is_read=i % 2 == 0,
                has_attachments=False,
                uid=i,
            )
            for i in range(1, 5)
        ],
    )

    # Monkeypatch factory for this account via provider=memory and inject instance
    import mail_core.sync.engine as engine_mod

    original = engine_mod.build_provider

    def _build(account, store=None):
        if account.provider == "memory":
            return provider
        return original(account, store)

    engine_mod.build_provider = _build
    try:
        with Session() as session:
            acc = create_account(
                session,
                email=f"mem-{uuid.uuid4().hex[:8]}@example.com",
                provider="memory",
                credential_ref="mem:x",
            )
            session.commit()
            account_id = acc.id

        result = sync_account_folders(account_id, worker_id="w-test", store=store)
        assert result["status"] == "ok"
        assert result["folders"] >= 1

        with Session() as session:
            folder = session.scalar(select(Folder).where(Folder.account_id == account_id))
            assert folder is not None
            folder_id = folder.id

        meta = sync_folder_metadata(account_id, folder_id, worker_id="w-test", store=store, max_pages=10)
        assert meta["status"] == "ok"
        assert meta["upserted"] == 4
        assert meta["exhausted"] is True

        with Session() as session:
            n = session.scalar(select(func.count()).select_from(Message).where(Message.account_id == account_id))
            assert n == 4
            # reconcile job enqueued
            jobs = session.scalars(
                select(WorkerJob).where(
                    WorkerJob.account_id == account_id,
                    WorkerJob.job_type == JobType.RECONCILE_FOLDER.value,
                )
            ).all()
            assert len(jobs) >= 1
    finally:
        engine_mod.build_provider = original
        set_credential_store(None)


@pytest.mark.skipif(not _imap_up(), reason="pymap IMAP not listening")
def test_live_imap_sync_via_worker_handler():
    store = DictCredentialStore()
    ref = f"test:alice-{uuid.uuid4().hex[:6]}"
    store.put(ref, os.environ.get("MAIL_CORE_IMAP_PASS", "alice-imap-pass"))
    set_credential_store(store)
    Session = get_session_factory()
    host = os.environ.get("MAIL_CORE_IMAP_HOST", "127.0.0.1")
    port = int(os.environ.get("MAIL_CORE_IMAP_PORT", "1143"))
    user = os.environ.get("MAIL_CORE_IMAP_USER", "alice@kkmail.test")

    with Session() as session:
        acc = create_account(
            session,
            email=f"imap-{uuid.uuid4().hex[:8]}@kkmail.test",
            provider=ProviderType.IMAP,
            credential_ref=ref,
            config={"imap_host": host, "imap_port": port, "imap_user": user, "use_ssl": False},
        )
        enqueue_job(session, job_type=JobType.SYNC_ACCOUNT_FOLDERS.value, account_id=acc.id)
        session.commit()
        account_id = acc.id

    # Drive worker claim loop for folders + metadata + reconcile
    for _ in range(20):
        with Session() as session:
            jobs = claim_jobs(session, worker_id="imap-worker", limit=1, account_id=account_id)
            if not jobs:
                session.commit()
                break
            handle_job(session, jobs[0])
            session.commit()

    with Session() as session:
        folders = session.scalars(select(Folder).where(Folder.account_id == account_id)).all()
        assert any(f.remote_id.upper() == "INBOX" for f in folders)
        msgs = session.scalars(select(Message).where(Message.account_id == account_id)).all()
        assert len(msgs) >= 1, "expected IMAP metadata sync to persist messages"
    set_credential_store(None)
