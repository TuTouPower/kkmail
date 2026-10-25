"""Flag deltas must patch flags only — never wipe subject/from via stub meta."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select

from mail_core.db.session import get_session_factory
from mail_core.mail.storage import Account, Folder, Message
from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta
from mail_core.providers.parsing.graph_delta import parse_graph_delta
from mail_core.sync import acquire_lease, apply_delta_page

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_flag_patches_bulk_load_messages_once():
    from mail_core.sync.delta import _apply_flag_patches

    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"flag-batch-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(account)
        session.flush()
        folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        messages = [
            Message(
                account_id=account.id,
                remote_id=f"batch-{index}",
                subject=f"Message {index}",
                from_address="sender@example.com",
                is_read=False,
                is_flagged=False,
            )
            for index in range(5)
        ]
        session.add_all(messages)
        session.flush()
        changes = [
            DeltaChange(
                kind="flag",
                remote_id=message.remote_id,
                flags={"is_read": True, "is_flagged": True},
            )
            for message in messages
        ]

        message_selects = 0

        def count_message_select(_conn, _cursor, statement, _params, _context, _many):
            nonlocal message_selects
            normalized = " ".join(statement.lower().split())
            if (
                normalized.startswith("select")
                and " from messages " in normalized
                and "messages.account_id" in normalized
                and "messages.remote_id" in normalized
            ):
                message_selects += 1

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", count_message_select)
        try:
            changed_count, touched = _apply_flag_patches(
                session,
                account_id=account.id,
                folder_id=folder.id,
                changes=changes,
            )
        finally:
            event.remove(engine, "before_cursor_execute", count_message_select)

        assert message_selects == 1
        assert changed_count == len(messages)
        assert len(touched) == len(messages)
        assert all(message.is_read and message.is_flagged for message in messages)
        session.commit()


def test_flag_delta_does_not_wipe_subject():
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc = Account(email=f"flag-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        msg = Message(
            account_id=acc.id,
            remote_id="rid-1",
            subject="KeepMe",
            from_address="a@b.c",
            from_name="Alice",
            sort_time=now,
            is_read=False,
            is_flagged=False,
        )
        session.add(msg)
        session.flush()
        lease = acquire_lease(session, account_id=acc.id, owner_id="w", ttl=timedelta(minutes=5))
        # Stub meta with empty subject/from — old code would wipe; new code patches flags only.
        stub = RemoteMessageMeta(
            remote_id="rid-1",
            subject="",
            from_address="",
            from_name=None,
            sort_time=now,
            is_read=True,
            has_attachments=False,
        )
        page = DeltaPage(
            changes=[
                DeltaChange(kind="flag", remote_id="rid-1", meta=stub, flags={"is_read": True}),
            ],
            next_cursor={"historyId": "2"},
            exhausted=True,
        )
        apply_delta_page(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=page,
        )
        session.commit()
        loaded = session.scalar(select(Message).where(Message.id == msg.id))
        assert loaded.subject == "KeepMe"
        assert loaded.from_address == "a@b.c"
        assert loaded.is_read is True


def test_graph_partial_delta_preserves_status_fields_not_returned_by_provider():
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc = Account(email=f"graph-flags-{uuid.uuid4().hex[:8]}@example.com", provider="graph")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="inbox", name="Inbox", role="inbox")
        session.add(folder)
        session.flush()
        messages = [
            Message(
                account_id=acc.id,
                remote_id="read-only",
                subject="Read only",
                from_address="sender@example.com",
                sort_time=now,
                is_read=False,
                is_flagged=True,
            ),
            Message(
                account_id=acc.id,
                remote_id="flag-only",
                subject="Flag only",
                from_address="sender@example.com",
                sort_time=now,
                is_read=True,
                is_flagged=False,
            ),
            Message(
                account_id=acc.id,
                remote_id="upsert-read-only",
                subject="Old subject",
                from_address="sender@example.com",
                sort_time=now,
                is_read=True,
                is_flagged=True,
            ),
            Message(
                account_id=acc.id,
                remote_id="unflagged",
                subject="Unflagged",
                from_address="sender@example.com",
                sort_time=now,
                is_read=True,
                is_flagged=True,
            ),
        ]
        session.add_all(messages)
        session.flush()
        lease = acquire_lease(session, account_id=acc.id, owner_id="graph-test", ttl=timedelta(minutes=5))
        page = parse_graph_delta(
            {
                "value": [
                    {"id": "read-only", "isRead": True},
                    {"id": "flag-only", "flag": {"flagStatus": "flagged"}},
                    {
                        "id": "upsert-read-only",
                        "subject": "Updated subject",
                        "from": {"emailAddress": {"address": "sender@example.com"}},
                        "receivedDateTime": now.isoformat(),
                        "isRead": False,
                    },
                    {"id": "unflagged", "flag": {"flagStatus": "notFlagged"}},
                ]
            }
        )

        apply_delta_page(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=page,
        )
        session.commit()

        actual = {
            message.remote_id: (message.is_read, message.is_flagged)
            for message in session.scalars(select(Message).where(Message.account_id == acc.id))
        }
        assert actual == {
            "read-only": (True, True),
            "flag-only": (True, True),
            "upsert-read-only": (False, True),
            "unflagged": (True, False),
        }


def test_delta_explicit_flag_patch_does_not_fall_back_to_unrelated_meta_read_state():
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc = Account(email=f"partial-flags-{uuid.uuid4().hex[:8]}@example.com", provider="gmail")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        message = Message(
            account_id=acc.id,
            remote_id="starred-unread",
            subject="Keep unread",
            from_address="sender@example.com",
            sort_time=now,
            is_read=True,
            is_flagged=False,
        )
        session.add(message)
        session.flush()
        lease = acquire_lease(session, account_id=acc.id, owner_id="partial-flag-test", ttl=timedelta(minutes=5))
        meta = RemoteMessageMeta(
            remote_id=message.remote_id,
            subject=message.subject,
            from_address=message.from_address,
            from_name=None,
            sort_time=now,
            is_read=False,
            has_attachments=None,
        )

        apply_delta_page(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=DeltaPage(
                changes=[
                    DeltaChange(
                        kind="flag",
                        remote_id=message.remote_id,
                        meta=meta,
                        flags={"is_flagged": True},
                    )
                ],
                next_cursor=None,
                exhausted=True,
            ),
        )
        session.commit()

        loaded = session.get(Message, message.id)
        assert loaded.is_read is True
        assert loaded.is_flagged is True


def test_multilocation_flag_update_refreshes_all_folder_stats():
    """P2-02: updating is_read on a multi-location message refreshes all affected folders."""
    from mail_core.mail.storage.models import FolderStats, MessageLocation

    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"multi-loc-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(account)
        session.flush()

        folder_a = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        folder_b = Folder(account_id=account.id, remote_id="ALL", name="All Mail", role="archive")
        session.add_all([folder_a, folder_b])
        session.flush()

        msg = Message(
            account_id=account.id,
            remote_id="multi-msg-1",
            subject="Multi-location test",
            from_address="sender@example.com",
            is_read=False,
        )
        session.add(msg)
        session.flush()

        loc_a = MessageLocation(message_id=msg.id, folder_id=folder_a.id, uid=10)
        loc_b = MessageLocation(message_id=msg.id, folder_id=folder_b.id, uid=20)
        session.add_all([loc_a, loc_b])
        session.flush()

        from mail_core.mail.storage.folder_stats import recompute_folder_stats

        recompute_folder_stats(session, folder_a.id)
        recompute_folder_stats(session, folder_b.id)
        folder_a_id = folder_a.id
        folder_b_id = folder_b.id
        account_id = account.id
        session.commit()

    with Session() as session:
        # Pre-check: both folders have 1 unread message
        stats_a = session.get(FolderStats, folder_a_id)
        stats_b = session.get(FolderStats, folder_b_id)
        assert stats_a.unread_count == 1
        assert stats_b.unread_count == 1

        lease = acquire_lease(session, account_id=account_id, owner_id="multi-test", ttl=timedelta(minutes=5))
        # Sync delta for folder_a with is_read=True
        apply_delta_page(
            session,
            account_id=account_id,
            folder_id=folder_a_id,
            fencing_token=lease.fencing_token,
            page=DeltaPage(
                changes=[
                    DeltaChange(
                        kind="flag",
                        remote_id="multi-msg-1",
                        flags={"is_read": True},
                    )
                ],
                next_cursor=None,
                exhausted=True,
            ),
        )
        session.commit()

    with Session() as session:
        # Verify: BOTH folder_a AND folder_b have unread_count updated to 0
        stats_a = session.get(FolderStats, folder_a_id)
        stats_b = session.get(FolderStats, folder_b_id)
        assert stats_a.unread_count == 0
        assert stats_b.unread_count == 0


def test_multilocation_delete_single_location_refreshes_stats_and_emits_event():
    """P2-03: removing a message location updates folder stats and emits event even if message stays in other folders."""
    from mail_core.mail.storage.models import FolderStats, MessageLocation, OutboxEvent

    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"del-loc-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(account)
        session.flush()

        folder_a = Folder(account_id=account.id, remote_id="LABEL1", name="Label 1", role="other")
        folder_b = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add_all([folder_a, folder_b])
        session.flush()

        msg = Message(
            account_id=account.id,
            remote_id="multi-msg-del-1",
            subject="Multi-location delete test",
            from_address="sender@example.com",
            is_read=True,
        )
        session.add(msg)
        session.flush()

        loc_a = MessageLocation(message_id=msg.id, folder_id=folder_a.id, uid=10)
        loc_b = MessageLocation(message_id=msg.id, folder_id=folder_b.id, uid=20)
        session.add_all([loc_a, loc_b])
        session.flush()

        from mail_core.mail.storage.folder_stats import recompute_folder_stats

        recompute_folder_stats(session, folder_a.id)
        recompute_folder_stats(session, folder_b.id)
        folder_a_id = folder_a.id
        folder_b_id = folder_b.id
        account_id = account.id
        msg_id = msg.id
        session.commit()

    with Session() as session:
        stats_a = session.get(FolderStats, folder_a_id)
        stats_b = session.get(FolderStats, folder_b_id)
        assert stats_a.total_count == 1
        assert stats_b.total_count == 1

        lease = acquire_lease(session, account_id=account_id, owner_id="del-test", ttl=timedelta(minutes=5))
        apply_delta_page(
            session,
            account_id=account_id,
            folder_id=folder_a_id,
            fencing_token=lease.fencing_token,
            page=DeltaPage(
                changes=[
                    DeltaChange(
                        kind="delete",
                        remote_id="multi-msg-del-1",
                    )
                ],
                next_cursor=None,
                exhausted=True,
            ),
        )
        session.commit()

    with Session() as session:
        # Folder A count becomes 0, Folder B remains 1
        stats_a = session.get(FolderStats, folder_a_id)
        stats_b = session.get(FolderStats, folder_b_id)
        assert stats_a.total_count == 0
        assert stats_b.total_count == 1

        # Message is not orphaned, still exists
        remaining_msg = session.get(Message, msg_id)
        assert remaining_msg is not None

        # Verify invalidate event was emitted for folder A
        events = list(
            session.scalars(
                select(OutboxEvent)
                .where(OutboxEvent.account_id == account_id)
                .order_by(OutboxEvent.id.desc())
                .limit(5)
            ).all()
        )
        types = [e.event_type for e in events]
        assert "message.upserted" in types or "folder.stats_updated" in types
