from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import mail_core.sync.delta as delta
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage.models import (
    Account,
    AccountSyncLease,
    Folder,
    FolderStats,
    Message,
    MessageSearch,
    OutboxEvent,
    SyncCheckpoint,
)
from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta
from mail_core.sync.leases import FencingMismatch


def test_delta_apply_counts_only_changed_upserts(monkeypatch):
    outcomes = [
        SimpleNamespace(changed=True, created=True, message=SimpleNamespace(id=uuid.uuid4(), thread_id=None)),
        SimpleNamespace(changed=False, created=False, message=SimpleNamespace(id=uuid.uuid4(), thread_id=None)),
    ]
    monkeypatch.setattr(delta, "assert_fencing", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(delta, "upsert_messages", lambda *_args, **_kwargs: outcomes)
    monkeypatch.setattr(delta, "upsert_message_search", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(delta, "_apply_flag_patches", lambda *_args, **_kwargs: (0, []))
    monkeypatch.setattr(delta, "messages_upserted_event", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(delta, "recompute_folder_stats", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(delta, "commit_checkpoint", lambda *_args, **_kwargs: None)

    class Session:
        # Package C test-contract adaptation: apply_delta_page legitimately
        # queries shared folders via session.scalars(...).all(); the fake
        # models "no shared folders" instead of lacking the method.
        def add(self, _value):
            pass

        def flush(self):
            pass

        def scalars(self, *_args, **_kwargs):
            return SimpleNamespace(all=lambda: [])

        def scalar(self, *_args, **_kwargs):
            return None

    metas = [
        RemoteMessageMeta(
            remote_id=f"remote-{index}",
            subject="subject",
            from_address="sender@example.test",
            from_name=None,
            sort_time=None,
            is_read=None,
            has_attachments=None,
        )
        for index in range(2)
    ]
    page = DeltaPage(
        changes=[DeltaChange(kind="upsert", remote_id=meta.remote_id, meta=meta) for meta in metas],
        next_cursor={"historyId": "next"},
        exhausted=False,
    )

    result = delta.apply_delta_page(
        Session(),
        account_id=uuid.uuid4(),
        folder_id=uuid.uuid4(),
        fencing_token=1,
        page=page,
    )

    assert result.upserted == 1


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_pg_delta_result_counts_and_persistence_side_effects():
    """True PostgreSQL verification for delta changed count and persistence side effects."""
    Session = get_session_factory()
    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # 1. Baseline setup: real Account, Folder, Lease, Checkpoint, FolderStats
    with Session() as session:
        session.add(
            Account(
                id=account_id,
                email=f"delta-{uuid.uuid4().hex[:8]}@example.com",
                provider="imap",
                credential_ref=None,
                sync_enabled=True,
            )
        )
        session.add(
            Folder(
                id=folder_id,
                account_id=account_id,
                remote_id="INBOX",
                name="INBOX",
                role="inbox",
            )
        )
        session.add(
            AccountSyncLease(
                account_id=account_id,
                owner_id="w-delta-test",
                lease_expires_at=now + timedelta(minutes=5),
                heartbeat_at=now,
                fencing_token=1,
            )
        )
        session.add(
            SyncCheckpoint(
                account_id=account_id,
                folder_id=folder_id,
                cursor={"modseq": 10},
                fencing_token=1,
                full_scan_complete=True,
            )
        )
        session.add(
            FolderStats(
                folder_id=folder_id,
                total_count=0,
                unread_count=0,
                updated_at=now,
            )
        )
        session.commit()

    # 2. Seed initial two messages via unmocked apply_delta_page
    meta1_init = RemoteMessageMeta(
        remote_id="remote-1",
        subject="Initial Subject 1",
        from_address="sender1@example.test",
        from_name="Sender One",
        sort_time=now,
        is_read=False,
        has_attachments=False,
    )
    meta2_init = RemoteMessageMeta(
        remote_id="remote-2",
        subject="Initial Subject 2",
        from_address="sender2@example.test",
        from_name="Sender Two",
        sort_time=now,
        is_read=True,
        has_attachments=False,
    )
    initial_page = DeltaPage(
        changes=[
            DeltaChange(kind="upsert", remote_id="remote-1", meta=meta1_init),
            DeltaChange(kind="upsert", remote_id="remote-2", meta=meta2_init),
        ],
        next_cursor={"modseq": 20},
        exhausted=True,
    )

    with Session() as session:
        init_result = delta.apply_delta_page(
            session,
            account_id=account_id,
            folder_id=folder_id,
            fencing_token=1,
            page=initial_page,
        )
        session.commit()
        assert init_result.upserted == 2

    # Get baseline outbox event IDs so we can cleanly isolate subsequent events
    with Session() as session:
        baseline_outbox_ids = set(
            session.scalars(
                select(OutboxEvent.id).where(OutboxEvent.account_id == account_id)
            ).all()
        )

    # 3. Apply delta page with two messages:
    # - remote-1: subject changes ("Updated Subject 1") and marked read (True) -> changed
    # - remote-2: exact identical metadata as in DB -> untouched (unchanged)
    meta1_changed = RemoteMessageMeta(
        remote_id="remote-1",
        subject="Updated Subject 1",
        from_address="sender1@example.test",
        from_name="Sender One",
        sort_time=now,
        is_read=True,
        has_attachments=False,
    )
    meta2_same = RemoteMessageMeta(
        remote_id="remote-2",
        subject="Initial Subject 2",
        from_address="sender2@example.test",
        from_name="Sender Two",
        sort_time=now,
        is_read=True,
        has_attachments=False,
    )

    delta_page = DeltaPage(
        changes=[
            DeltaChange(kind="upsert", remote_id="remote-1", meta=meta1_changed),
            DeltaChange(kind="upsert", remote_id="remote-2", meta=meta2_same),
        ],
        next_cursor={"modseq": 30},
        exhausted=True,
    )

    with Session() as session:
        result = delta.apply_delta_page(
            session,
            account_id=account_id,
            folder_id=folder_id,
            fencing_token=1,
            page=delta_page,
        )
        session.commit()

        # Exact assertion: only the changed message counts as upserted!
        assert result.upserted == 1

    # 4. Verify DB persistence and side-effects
    with Session() as session:
        msg1 = session.scalar(
            select(Message).where(Message.account_id == account_id, Message.remote_id == "remote-1")
        )
        msg2 = session.scalar(
            select(Message).where(Message.account_id == account_id, Message.remote_id == "remote-2")
        )
        assert msg1 is not None and msg2 is not None
        assert msg1.subject == "Updated Subject 1"
        assert msg1.is_read is True
        assert msg2.subject == "Initial Subject 2"

        # Search index updated for msg1
        search1 = session.get(MessageSearch, msg1.id)
        assert search1 is not None
        assert search1.subject == "Updated Subject 1"

        # Folder stats updated
        stats = session.get(FolderStats, folder_id)
        assert stats is not None
        assert stats.total_count == 2
        assert stats.unread_count == 0  # both are now read

        # Outbox events: verify only changed message ID is included in new MESSAGE_UPSERTED events
        new_events = list(
            session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.account_id == account_id, OutboxEvent.id.not_in(baseline_outbox_ids))
                .order_by(OutboxEvent.id.asc())
            ).all()
        )
        assert len(new_events) >= 1
        upsert_events = [e for e in new_events if e.event_type == OutboxEventType.MESSAGE_UPSERTED.value]
        assert len(upsert_events) == 1
        event_msg_ids = upsert_events[0].payload.get("message_ids", [])
        assert str(msg1.id) in event_msg_ids
        assert str(msg2.id) not in event_msg_ids, "unchanged message must not be emitted in MESSAGE_UPSERTED outbox"

        # Checkpoint cursor updated
        checkpoint = session.get(SyncCheckpoint, (account_id, folder_id))
        assert checkpoint is not None
        assert checkpoint.cursor == {"modseq": 30}
        assert checkpoint.fencing_token == 1


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_pg_delta_invalid_fencing_token_rejects():
    """Invalid fencing token must raise FencingMismatch and block commit."""
    Session = get_session_factory()
    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    now = datetime.now(timezone.utc)

    with Session() as session:
        session.add(
            Account(
                id=account_id,
                email=f"fencing-{uuid.uuid4().hex[:8]}@example.com",
                provider="imap",
                credential_ref=None,
                sync_enabled=True,
            )
        )
        session.add(
            Folder(
                id=folder_id,
                account_id=account_id,
                remote_id="INBOX",
                name="INBOX",
                role="inbox",
            )
        )
        session.add(
            AccountSyncLease(
                account_id=account_id,
                owner_id="w-fence-test",
                lease_expires_at=now + timedelta(minutes=5),
                heartbeat_at=now,
                fencing_token=5,
            )
        )
        session.commit()

    meta = RemoteMessageMeta(
        remote_id="remote-fence",
        subject="Fence Subject",
        from_address="fence@example.test",
        from_name="Fence",
        sort_time=now,
        is_read=False,
        has_attachments=False,
    )
    page = DeltaPage(
        changes=[DeltaChange(kind="upsert", remote_id="remote-fence", meta=meta)],
        next_cursor={"modseq": 99},
        exhausted=True,
    )

    with Session() as session:
        with pytest.raises(FencingMismatch):
            delta.apply_delta_page(
                session,
                account_id=account_id,
                folder_id=folder_id,
                fencing_token=1,  # Lease has 5; token 1 is stale / rejected
                page=page,
            )
        session.rollback()

    # Verify no message was persisted and no checkpoint created
    with Session() as session:
        msg = session.scalar(
            select(Message).where(Message.account_id == account_id, Message.remote_id == "remote-fence")
        )
        assert msg is None
        cp = session.get(SyncCheckpoint, (account_id, folder_id))
        assert cp is None
