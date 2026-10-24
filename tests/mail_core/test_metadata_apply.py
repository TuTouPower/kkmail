from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select, func

from mail_core.db.session import get_session_factory
from mail_core.mail.storage import Account, Folder, FolderStats, Message, MessageArchiveState, OutboxEvent
from mail_core.providers.base import MetadataPage, RemoteMessageMeta
from mail_core.sync import acquire_lease, apply_metadata_page

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_apply_metadata_page_writes_messages_stats_outbox_checkpoint():
    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"meta-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        lease = acquire_lease(session, account_id=acc.id, owner_id="w1", ttl=timedelta(minutes=5))
        page = MetadataPage(
            items=[
                RemoteMessageMeta(
                    remote_id="101",
                    subject="Hello",
                    from_address="a@b.c",
                    from_name="A",
                    sort_time=datetime.now(timezone.utc),
                    is_read=False,
                    has_attachments=False,
                    uid=101,
                ),
                RemoteMessageMeta(
                    remote_id="102",
                    subject="World",
                    from_address="c@d.e",
                    from_name=None,
                    sort_time=datetime.now(timezone.utc),
                    is_read=True,
                    has_attachments=True,
                    uid=102,
                ),
            ],
            next_cursor={"uid_next": 103, "uidvalidity": 9},
            exhausted=True,
        )
        result = apply_metadata_page(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=page,
        )
        session.commit()
        assert result.upserted == 2
        assert result.exhausted
        msgs = session.scalars(select(Message).where(Message.account_id == acc.id)).all()
        assert len(msgs) == 2
        archives = session.scalars(select(MessageArchiveState)).all()
        assert all(a.state == "metadata_synced" for a in archives if a.message_id in {m.id for m in msgs})
        stats = session.get(FolderStats, folder.id)
        assert stats.total_count == 2
        assert stats.unread_count == 1
        events = session.scalars(
            select(OutboxEvent).where(OutboxEvent.account_id == acc.id).order_by(OutboxEvent.id)
        ).all()
        # One batched upsert event per page (not per message) + one stats event.
        assert [e.event_type for e in events] == ["message.upserted", "folder.stats_updated"]
        assert sorted(events[0].payload["message_ids"]) == sorted(str(m.id) for m in msgs)

        # Re-applying an unchanged page writes no message updates and no upsert event.
        before = {m.id: m.updated_at for m in msgs}
        again = apply_metadata_page(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=page,
        )
        session.commit()
        assert again.upserted == 2
        for m in session.scalars(select(Message).where(Message.account_id == acc.id)):
            assert m.updated_at == before[m.id]
        n_upsert = session.scalar(
            select(func.count())
            .select_from(OutboxEvent)
            .where(OutboxEvent.account_id == acc.id, OutboxEvent.event_type == "message.upserted")
        )
        assert n_upsert == 1


def test_upsert_messages_and_search_index_batch_page_work():
    from mail_core.mail.storage import MessageBody, MessageSearch
    from mail_core.search.index import upsert_message_search_batch
    from mail_core.sync.metadata import upsert_messages

    Session = get_session_factory()
    with Session() as session:
        account = Account(email=f"meta-batch-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(account)
        session.flush()
        folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        now = datetime.now(timezone.utc)
        metas = [
            RemoteMessageMeta(
                remote_id=f"batch-{index}",
                subject=f"Subject {index}",
                from_address=f"sender{index}@example.com",
                from_name=None,
                sort_time=now,
                is_read=False,
                has_attachments=False,
                snippet=f"snippet {index}",
            )
            for index in range(5)
        ]

        flush_count = 0

        def count_flush(_session, _flush_context, _instances):
            nonlocal flush_count
            flush_count += 1

        event.listen(session, "before_flush", count_flush)
        try:
            outcomes = upsert_messages(
                session, account_id=account.id, folder_id=folder.id, metas=metas
            )
        finally:
            event.remove(session, "before_flush", count_flush)
        assert flush_count == 1

        session.add(
            MessageBody(message_id=outcomes[0].message.id, text_plain="full archived body")
        )
        session.flush()

        select_counts = {"message_bodies": 0, "message_search": 0}

        def count_index_select(_conn, _cursor, statement, _params, _context, _many):
            normalized = statement.lstrip().lower()
            if not normalized.startswith("select"):
                return
            for table in select_counts:
                if f"from {table}" in normalized:
                    select_counts[table] += 1

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", count_index_select)
        try:
            upsert_message_search_batch(
                session, messages=[outcome.message for outcome in outcomes]
            )
        finally:
            event.remove(engine, "before_cursor_execute", count_index_select)

        assert select_counts == {"message_bodies": 1, "message_search": 1}
        indexed = {
            row.message_id: row
            for row in session.scalars(
                select(MessageSearch).where(
                    MessageSearch.message_id.in_([o.message.id for o in outcomes])
                )
            )
        }
        assert len(indexed) == len(metas)
        assert indexed[outcomes[0].message.id].body_text == "full archived body"
        assert indexed[outcomes[1].message.id].body_text == "snippet 1"
        session.commit()


@pytest.mark.parametrize("sync_path", ("metadata", "delta"))
def test_sync_paths_rethread_unchanged_outcome_when_parent_arrives(sync_path):
    from mail_core.mail.storage import Thread, ThreadMessage
    from mail_core.providers.base import DeltaChange, DeltaPage
    from mail_core.sync.delta import apply_delta_page

    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        account = Account(email=f"thread-{uuid.uuid4().hex[:8]}@example.com", provider="gmail")
        session.add(account)
        session.flush()
        folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        lease = acquire_lease(session, account_id=account.id, owner_id="thread-test", ttl=timedelta(minutes=5))

        def apply_upserts(items, cursor, exhausted=False):
            if sync_path == "metadata":
                apply_metadata_page(
                    session,
                    account_id=account.id,
                    folder_id=folder.id,
                    fencing_token=lease.fencing_token,
                    page=MetadataPage(
                        items=items,
                        next_cursor={"uid_next": 3, "uidvalidity": 7},
                        exhausted=exhausted,
                    ),
                )
            else:
                apply_delta_page(
                    session,
                    account_id=account.id,
                    folder_id=folder.id,
                    fencing_token=lease.fencing_token,
                    page=DeltaPage(
                        changes=[DeltaChange(kind="upsert", remote_id=meta.remote_id, meta=meta) for meta in items],
                        next_cursor={"historyId": cursor},
                        exhausted=exhausted,
                    ),
                )

        child_meta = RemoteMessageMeta(
            remote_id="thread-child",
            subject="Re: Root",
            from_address="child@example.com",
            from_name=None,
            sort_time=now,
            is_read=False,
            has_attachments=False,
            internet_message_id="<child@example.com>",
            in_reply_to="<parent@example.com>",
            references="<parent@example.com>",
            uid=2,
        )
        apply_upserts([child_meta], "1")
        child = session.scalar(select(Message).where(Message.remote_id == child_meta.remote_id))
        assert child is not None and child.thread_id is not None
        original_thread_id = child.thread_id

        apply_upserts([child_meta], "2")
        assert child.thread_id == original_thread_id
        assert session.scalar(
            select(func.count()).select_from(Thread).where(Thread.account_id == account.id)
        ) == 1

        parent_meta = RemoteMessageMeta(
            remote_id="thread-parent",
            subject="Root",
            from_address="parent@example.com",
            from_name=None,
            sort_time=now,
            is_read=False,
            has_attachments=False,
            internet_message_id="<parent@example.com>",
            uid=1,
        )
        apply_upserts([parent_meta, child_meta], "3", exhausted=True)

        parent = session.scalar(select(Message).where(Message.remote_id == parent_meta.remote_id))
        assert parent is not None and parent.thread_id is not None
        assert parent.thread_id != original_thread_id
        assert child.thread_id == parent.thread_id
        child_threads = session.scalars(
            select(ThreadMessage.thread_id).where(ThreadMessage.message_id == child.id)
        ).all()
        assert child_threads == [parent.thread_id]
        events = session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.account_id == account.id, OutboxEvent.event_type == "message.upserted")
            .order_by(OutboxEvent.id)
        ).all()
        assert set(events[-1].payload["message_ids"]) == {str(parent.id), str(child.id)}
        session.commit()


def test_unknown_provider_time_does_not_erase_known_received_time():
    Session = get_session_factory()
    known_time = datetime(2026, 10, 20, 12, 30, tzinfo=timezone.utc)
    with Session() as session:
        account = Account(email=f"meta-time-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(account)
        session.flush()
        folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        lease = acquire_lease(session, account_id=account.id, owner_id="w-time", ttl=timedelta(minutes=5))
        initial_page = MetadataPage(
            items=[
                RemoteMessageMeta("known", "Known", "a@b.c", None, known_time, False, False),
                RemoteMessageMeta("unknown", "Unknown", "c@d.e", None, None, False, False),
            ],
            next_cursor={},
            exhausted=True,
        )
        apply_metadata_page(
            session,
            account_id=account.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=initial_page,
        )
        session.commit()
        account_id, folder_id = account.id, folder.id

    with Session() as session:
        lease = acquire_lease(session, account_id=account_id, owner_id="w-time", ttl=timedelta(minutes=5))
        page = MetadataPage(
            items=[RemoteMessageMeta("known", "Known", "a@b.c", None, None, False, False)],
            next_cursor={},
            exhausted=True,
        )
        apply_metadata_page(
            session,
            account_id=account_id,
            folder_id=folder_id,
            fencing_token=lease.fencing_token,
            page=page,
        )
        session.commit()
        rows = {
            message.remote_id: message.sort_time
            for message in session.scalars(select(Message).where(Message.account_id == account_id))
        }

    assert rows["known"] == known_time
    assert rows["unknown"] is None


def test_metadata_apply_preserves_fts_body_and_skips_outbox_on_replay():
    """Snippet must not overwrite MessageBody-backed FTS; replay must not flood outbox."""
    from mail_core.mail.storage.models import MessageBody, MessageSearch, SyncCheckpoint
    from mail_core.search.index import upsert_message_search

    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"fts-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        lease = acquire_lease(session, account_id=acc.id, owner_id="w1", ttl=timedelta(minutes=5))
        page = MetadataPage(
            items=[
                RemoteMessageMeta(
                    remote_id="201",
                    subject="Hello",
                    from_address="a@b.c",
                    from_name="A",
                    sort_time=datetime.now(timezone.utc),
                    is_read=False,
                    has_attachments=False,
                    snippet="short-snippet",
                    uid=201,
                ),
            ],
            next_cursor={"uid_next": 202, "uidvalidity": 1},
            exhausted=False,
        )
        apply_metadata_page(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=page,
        )
        session.flush()
        msg = session.scalar(select(Message).where(Message.account_id == acc.id))
        session.add(MessageBody(message_id=msg.id, text_plain="full archived body text here"))
        session.flush()
        upsert_message_search(session, message_id=msg.id)  # index full body
        session.commit()
        mid = msg.id
        account_id = acc.id
        folder_id = folder.id

    with Session() as session:
        lease = acquire_lease(session, account_id=account_id, owner_id="w1", ttl=timedelta(minutes=5))
        # Subject change triggers search upsert — must keep body_text from MessageBody
        page2 = MetadataPage(
            items=[
                RemoteMessageMeta(
                    remote_id="201",
                    subject="Hello again",
                    from_address="a@b.c",
                    from_name="A",
                    sort_time=datetime.now(timezone.utc),
                    is_read=False,
                    has_attachments=False,
                    snippet="short-snippet",
                    uid=201,
                ),
            ],
            next_cursor={"uid_next": 202, "uidvalidity": 1},
            exhausted=True,
        )
        apply_metadata_page(
            session,
            account_id=account_id,
            folder_id=folder_id,
            fencing_token=lease.fencing_token,
            page=page2,
        )
        session.commit()
        row = session.get(MessageSearch, mid)
        assert row is not None
        assert "full archived body" in (row.body_text or "")
        assert "short-snippet" not in (row.body_text or "") or "full archived" in row.body_text

        # Identical replay: no new outbox rows
        before = session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.account_id == account_id))
        apply_metadata_page(
            session,
            account_id=account_id,
            folder_id=folder_id,
            fencing_token=lease.fencing_token,
            page=page2,
        )
        session.commit()
        after = session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.account_id == account_id))
        assert after == before


def test_metadata_apply_preserves_unknown_attachment_state_and_updates_explicit_values():
    """Unknown provider attachment state must preserve the locally parsed MIME result."""
    Session = get_session_factory()
    now = datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc)
    with Session() as session:
        acc = Account(email=f"attachments-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        existing = [
            Message(
                account_id=acc.id,
                remote_id=remote_id,
                subject=remote_id,
                from_address="sender@example.com",
                sort_time=now,
                has_attachments=has_attachments,
            )
            for remote_id, has_attachments in (
                ("unknown-true", True),
                ("unknown-false", False),
                ("explicit-false", True),
                ("explicit-true", False),
            )
        ]
        session.add_all(existing)
        session.flush()
        lease = acquire_lease(session, account_id=acc.id, owner_id="metadata-test", ttl=timedelta(minutes=5))
        page = MetadataPage(
            items=[
                RemoteMessageMeta(
                    remote_id="unknown-true",
                    subject="unknown-true",
                    from_address="sender@example.com",
                    from_name=None,
                    sort_time=now,
                    is_read=False,
                    has_attachments=None,
                ),
                RemoteMessageMeta(
                    remote_id="unknown-false",
                    subject="unknown-false",
                    from_address="sender@example.com",
                    from_name=None,
                    sort_time=now,
                    is_read=False,
                    has_attachments=None,
                ),
                RemoteMessageMeta(
                    remote_id="explicit-false",
                    subject="explicit-false",
                    from_address="sender@example.com",
                    from_name=None,
                    sort_time=now,
                    is_read=False,
                    has_attachments=False,
                ),
                RemoteMessageMeta(
                    remote_id="explicit-true",
                    subject="explicit-true",
                    from_address="sender@example.com",
                    from_name=None,
                    sort_time=now,
                    is_read=False,
                    has_attachments=True,
                ),
            ],
            next_cursor=None,
            exhausted=True,
        )

        apply_metadata_page(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=page,
        )
        session.commit()

        actual = {
            message.remote_id: message.has_attachments
            for message in session.scalars(select(Message).where(Message.account_id == acc.id))
        }
        assert actual == {
            "unknown-true": True,
            "unknown-false": False,
            "explicit-false": False,
            "explicit-true": True,
        }


def test_delta_apply_preserves_full_scan_complete_and_indexes():
    from mail_core.providers.base import DeltaChange, DeltaPage
    from mail_core.mail.storage.models import MessageSearch, SyncCheckpoint
    from mail_core.sync.delta import apply_delta_page
    from mail_core.sync.checkpoints import commit_checkpoint

    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"delta-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        lease = acquire_lease(session, account_id=acc.id, owner_id="w1", ttl=timedelta(minutes=5))
        commit_checkpoint(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            cursor={"uid_next": 1},
            full_scan_complete=False,  # incomplete baseline
        )
        page = DeltaPage(
            changes=[
                DeltaChange(
                    kind="upsert",
                    remote_id="301",
                    meta=RemoteMessageMeta(
                        remote_id="301",
                        subject="D",
                        from_address="a@b.c",
                        from_name=None,
                        sort_time=datetime.now(timezone.utc),
                        is_read=True,
                        has_attachments=False,
                        internet_message_id="<m301@x>",
                        uid=301,
                    ),
                )
            ],
            next_cursor={"uid_next": 302},
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
        cp = session.get(SyncCheckpoint, {"account_id": acc.id, "folder_id": folder.id})
        assert cp.full_scan_complete is False  # must NOT force True
        msg = session.scalar(select(Message).where(Message.account_id == acc.id))
        assert session.get(MessageSearch, msg.id) is not None


def test_apply_metadata_page_empty_folder_initializes_zero_folder_stats():
    """AC-004: apply_metadata_page with 0 items on new folder must initialize FolderStats(0, 0)."""
    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"meta-empty-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="EMPTY", name="EMPTY", role="other")
        session.add(folder)
        session.flush()
        lease = acquire_lease(session, account_id=acc.id, owner_id="w1", ttl=timedelta(minutes=5))
        page = MetadataPage(items=[], next_cursor={"uid_validity": 1}, exhausted=True)

        # Precondition: no FolderStats row
        assert session.get(FolderStats, folder.id) is None

        apply_metadata_page(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=page,
        )
        session.commit()

        stats = session.get(FolderStats, folder.id)
        assert stats is not None
        assert stats.total_count == 0
        assert stats.unread_count == 0
