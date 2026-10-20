from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, func

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.db.session import get_session_factory
from mail_core.mail.storage import Folder, Message
from mail_core.providers.base import RemoteFolder, RemoteMessageMeta
from mail_core.providers.stub_memory import MemoryProvider
from mail_core.sync import sync_account_folders, sync_folder_delta, sync_folder_metadata
import mail_core.sync.engine as engine_mod
import mail_core.sync.delta as delta_mod

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_memory_incremental_delta_upsert_flag_delete():
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    now = datetime.now(timezone.utc)
    provider = MemoryProvider(folders=[RemoteFolder("INBOX", "INBOX", "inbox")], page_size=10)
    provider.seed(
        "INBOX",
        [RemoteMessageMeta("1", "One", "a@b.c", "A", now, False, False, uid=1)],
    )
    originals = (engine_mod.build_provider, delta_mod.build_provider)

    def _build(account, store=None):
        return provider

    engine_mod.build_provider = delta_mod.build_provider = _build
    Session = get_session_factory()
    try:
        with Session() as session:
            acc = create_account(
                session,
                email=f"delta-{uuid.uuid4().hex[:8]}@ex.com",
                provider="memory",
                credential_ref="r",
            )
            session.commit()
            account_id = acc.id
        assert sync_account_folders(account_id, worker_id="w", store=store)["status"] == "ok"
        with Session() as session:
            folder_id = session.scalar(select(Folder.id).where(Folder.account_id == account_id))
        assert sync_folder_metadata(account_id, folder_id, worker_id="w", store=store)["exhausted"]

        # Incremental changes after baseline
        provider.append_message(
            "INBOX",
            RemoteMessageMeta("2", "Two", "a@b.c", "A", now, False, False, uid=2),
        )
        provider.flag_message("INBOX", "1", is_read=True)
        provider.remove_message("INBOX", "1")

        result = sync_folder_delta(account_id, folder_id, worker_id="w", store=store, max_pages=5)
        assert result["status"] == "ok"
        assert result["upserted"] + result["flagged"] >= 1
        assert result["deleted"] >= 1

        with Session() as session:
            remotes = set(
                session.scalars(select(Message.remote_id).where(Message.account_id == account_id)).all()
            )
            assert "2" in remotes
            assert "1" not in remotes
    finally:
        engine_mod.build_provider, delta_mod.build_provider = originals
        set_credential_store(None)
