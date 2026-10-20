from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, func

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
