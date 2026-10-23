from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.blobs.archive import claim_archive_batch, run_archive_batch
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


def test_archive_claim_excludes_messages_without_provider_remote_id():
    Session = get_session_factory()
    with Session() as session:
        account = create_account(
            session,
            email=f"local-only-archive-{uuid.uuid4().hex[:8]}@example.com",
            provider="stub",
            credential_ref="local-only",
        )
        message = Message(
            account_id=account.id,
            remote_id=None,
            subject="Cached only",
            from_address="sender@example.com",
        )
        session.add(message)
        session.flush()
        state = MessageArchiveState(message_id=message.id, state=ArchiveState.ARCHIVE_PENDING.value)
        session.add(state)
        session.commit()
        message_id, account_id = message.id, account.id

    with Session() as session:
        claimed = claim_archive_batch(
            session,
            account_id=account_id,
            worker_id="local-only-test",
            limit=10,
            recent_days=7,
        )
        assert claimed == []
        state = session.get(MessageArchiveState, message_id)
        assert state is not None and state.state == ArchiveState.ARCHIVE_PENDING.value
        assert state.claimed_by is None


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

    original_engine = engine_mod.build_provider
    original_archive = archive_mod.build_provider
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
        engine_mod.build_provider = original_engine
        archive_mod.build_provider = original_archive
        set_credential_store(None)


def test_archive_batch_reuses_imap_session_across_messages():
    """AC-004: run_archive_batch reuses single IMAP session across multiple messages in same batch."""
    from unittest.mock import MagicMock, patch
    from mail_core.providers.imap import ImapProvider

    Session = get_session_factory()
    store = DictCredentialStore()
    set_credential_store(store)
    original_archive = archive_mod.build_provider

    try:
        with Session() as session:
            account = create_account(
                session,
                email=f"imap-reuse-{uuid.uuid4().hex[:8]}@example.com",
                provider="imap",
                credential_ref="cred-reuse",
            )
            account_id = account.id
            folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
            session.add(folder)
            session.flush()

            now = datetime.now(timezone.utc)
            for i in range(3):
                msg = Message(
                    account_id=account.id,
                    remote_id=f"100\x1fINBOX\x1f{i + 1}",
                    subject=f"Msg {i}",
                    from_address="sender@example.com",
                    sort_time=now,
                )
                session.add(msg)
                session.flush()
                session.add(MessageArchiveState(message_id=msg.id, state=ArchiveState.ARCHIVE_PENDING.value))
            session.commit()

        mock_imap_client = MagicMock()
        mock_imap_client.login.return_value = ("OK", [b"LOGIN completed"])
        mock_imap_client.select.return_value = ("OK", [b"10"])
        mock_imap_client.uid.return_value = ("OK", [(b"1", b"From: sender@example.com\r\nSubject: Hi\r\n\r\nBody")])

        with patch("imaplib.IMAP4_SSL", return_value=mock_imap_client):
            imap_provider = ImapProvider(
                host="imap.example.com",
                port=993,
                username="test@example.com",
                password="pwd",
            )
            archive_mod.build_provider = lambda *a, **kw: imap_provider
            res = run_archive_batch(
                account_id=account_id,
                worker_id="w-reuse",
                store=store,
                payload={"batch_size": 3},
            )
            assert res["status"] == "ok"
            assert res["completed"] == 3

            # Only ONE connect / login was issued for all 3 messages!
            assert mock_imap_client.login.call_count == 1
            # Logout called at end of batch session
            assert mock_imap_client.logout.call_count == 1
    finally:
        archive_mod.build_provider = original_archive
        set_credential_store(None)
