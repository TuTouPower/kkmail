from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, func

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.db.session import get_session_factory
from mail_core.mail.application.remote_ops import enqueue_remote_operation
from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.mail.storage import Folder, Message, MessageLocation, RemoteOperation, SyncCheckpoint
from mail_core.providers.base import RemoteFolder, RemoteMessageMeta
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.sync import push_remote_operations, reconcile_folder, sync_account_folders, sync_folder_metadata
import mail_core.sync.engine as engine_mod
import mail_core.sync.reconcile as reconcile_mod
import mail_core.sync.remote_push as push_mod

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _patch_provider(provider: MemoryProvider):
    originals = {
        "engine": engine_mod.build_provider,
        "reconcile": reconcile_mod.build_provider,
        "push": push_mod.build_provider,
    }

    def _build(account, store=None):
        return provider

    engine_mod.build_provider = _build
    reconcile_mod.build_provider = _build
    push_mod.build_provider = _build
    return originals


def _restore(originals):
    engine_mod.build_provider = originals["engine"]
    reconcile_mod.build_provider = originals["reconcile"]
    push_mod.build_provider = originals["push"]


def test_push_mark_read_and_reconcile_deletes():
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    provider.seed(
        "INBOX",
        [
            RemoteMessageMeta("1", "Keep", "a@b.c", "A", now, False, False, uid=1),
            RemoteMessageMeta("2", "Gone", "a@b.c", "A", now, False, False, uid=2),
        ],
    )
    originals = _patch_provider(provider)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"rop2-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            session.commit()
            account_id = acc.id

        assert sync_account_folders(account_id, worker_id="w", store=store)["status"] == "ok"
        with Session() as session:
            folder_id = session.scalar(select(Folder.id).where(Folder.account_id == account_id))
        assert sync_folder_metadata(account_id, folder_id, worker_id="w", store=store)["exhausted"] is True

        # enqueue mark_read for message 1
        with Session() as session:
            enqueue_remote_operation(
                session,
                account_id=account_id,
                entity_key="msg:1",
                op_type="mark_read",
                desired_state={"remote_id": "1", "folder_remote_id": "INBOX", "is_read": True},
            )
            session.commit()

        pushed = push_remote_operations(account_id, worker_id="w", store=store)
        assert pushed["status"] == "ok"
        assert pushed["pushed"] == 1
        assert provider.messages["INBOX"][0].is_read is True

        with Session() as session:
            op = session.scalar(select(RemoteOperation).where(RemoteOperation.account_id == account_id))
            assert op.status == RemoteOperationStatus.DONE.value

        # Remote deletes message 2; full_scan_complete already true → reconcile removes local
        provider.messages["INBOX"] = [m for m in provider.messages["INBOX"] if m.remote_id != "2"]
        result = reconcile_folder(account_id, folder_id, worker_id="w", store=store)
        assert result["status"] == "ok"
        assert result["deleted"] == 1

        with Session() as session:
            n = session.scalar(select(func.count()).select_from(Message).where(Message.account_id == account_id))
            assert n == 1
            # Ensure checkpoint still marks full scan complete
            cp = session.get(SyncCheckpoint, {"account_id": account_id, "folder_id": folder_id})
            assert cp.full_scan_complete is True
    finally:
        _restore(originals)
        set_credential_store(None)


def test_reconcile_skips_without_full_scan():
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    originals = _patch_provider(provider)
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"skip-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
            session.add(folder)
            session.flush()
            # checkpoint missing / incomplete
            session.commit()
            account_id, folder_id = acc.id, folder.id
        result = reconcile_folder(account_id, folder_id, worker_id="w", store=store)
        assert result["status"] == "skipped"
    finally:
        _restore(originals)
        set_credential_store(None)
