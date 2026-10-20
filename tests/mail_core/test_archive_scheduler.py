from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.blobs.archive import run_archive_batch
from mail_core.blobs.quota import check_quota
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import ArchiveState
from mail_core.mail.storage import Folder, Message, MessageArchiveState, MessageBlobLink
from mail_core.providers.base import RemoteFolder, RemoteMessageMeta
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.sync import sync_account_folders, sync_folder_metadata
import mail_core.sync.engine as engine_mod
import mail_core.blobs.archive as archive_mod

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_archive_batch_completes_and_respects_hard_quota(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")])
    metas = [
        RemoteMessageMeta(str(i), f"S{i}", "a@b.c", "A", now - timedelta(days=i), False, False, uid=i)
        for i in range(1, 4)
    ]
    mime = {str(i): (b"x" * 100) + str(i).encode() for i in range(1, 4)}
    provider.seed("INBOX", metas, mime)

    def _build(account, store=None):
        return provider

    engine_mod.build_provider = _build
    archive_mod.build_provider = _build
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(session, email=f"arch-{uuid.uuid4().hex[:8]}@ex.com", provider="memory", credential_ref="r")
            session.commit()
            account_id = acc.id
        sync_account_folders(account_id, worker_id="w", store=store)
        with Session() as session:
            folder_id = session.scalar(select(Folder.id).where(Folder.account_id == account_id))
        sync_folder_metadata(account_id, folder_id, worker_id="w", store=store)

        result = run_archive_batch(
            account_id=account_id,
            worker_id="w",
            store=store,
            payload={"batch_size": 10},
        )
        assert result["status"] == "ok"
        assert result["completed"] == 3

        with Session() as session:
            states = session.scalars(select(MessageArchiveState)).all()
            mine = [s for s in states if session.get(Message, s.message_id).account_id == account_id]
            assert all(s.state == ArchiveState.ARCHIVE_COMPLETE.value for s in mine)
            links = session.scalars(select(MessageBlobLink)).all()
            assert len([l for l in links if session.get(Message, l.message_id).account_id == account_id]) == 3

        # Hard quota pause: seed more messages then tiny hard limit
        provider.seed(
            "INBOX",
            metas
            + [
                RemoteMessageMeta("9", "New", "a@b.c", "A", now, False, False, uid=9),
            ],
            {**mime, "9": b"y" * 50},
        )
        # Force a new metadata row for msg 9
        with Session() as session:
            msg = Message(
                account_id=account_id,
                remote_id="9",
                subject="New",
                from_address="a@b.c",
                sort_time=now,
            )
            session.add(msg)
            session.flush()
            session.add(MessageArchiveState(message_id=msg.id, state=ArchiveState.METADATA_SYNCED.value))
            session.commit()

        used = check_quota(tmp_path).used_bytes
        paused = run_archive_batch(
            account_id=account_id,
            worker_id="w",
            store=store,
            payload={"batch_size": 5, "hard_limit_bytes": used},  # already at/over
        )
        assert paused["status"] == "paused_quota"
    finally:
        set_credential_store(None)
