"""B5b: batched reconcile deletes must be outcome-equivalent to the old loop.

The delete execution used to run three queries (plus a flush) per action
— roughly 600-800 round trips for a 200-action batch. It now prefetches
the batch's messages and locations with IN queries and decides orphans
with one more. This PG-gated test drives ``reconcile_folder`` end to end
and pins the observable contract: which messages are deleted, which
locations are removed, which messages survive, and exactly which outbox
events are emitted.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import select

import mail_core.sync.reconcile as reconcile_mod
from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage import Folder, Message, MessageLocation, OutboxEvent, SyncCheckpoint
from mail_core.providers.base import ReconcileAction
from mail_core.sync import reconcile_folder

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


class _StubProvider:
    def reconcile(self, _folder_remote_id, _local_ids):
        return [
            ReconcileAction(kind="delete", remote_id="gone-1"),
            ReconcileAction(kind="delete", remote_id="gone-2"),
            ReconcileAction(kind="delete", remote_id="ghost"),
            ReconcileAction(kind="keep", remote_id="keep-1"),
        ]


@pytestmark_db
def test_batched_reconcile_deletes_match_legacy_semantics(monkeypatch):
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    Session = get_session_factory()
    with Session() as session:
        acc = create_account(
            session,
            email=f"b5b-{uuid.uuid4().hex[:8]}@example.com",
            provider="memory",
            credential_ref="r",
        )
        session.flush()
        inbox = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        archive = Folder(account_id=acc.id, remote_id="Archive", name="Archive", role="archive")
        session.add_all([inbox, archive])
        session.flush()
        session.add(
            SyncCheckpoint(account_id=acc.id, folder_id=inbox.id, full_scan_complete=True, cursor={})
        )

        def _msg(remote_id: str) -> Message:
            msg = Message(
                id=uuid.uuid4(), account_id=acc.id, remote_id=remote_id,
                subject="s", from_address="a@b.c",
            )
            session.add(msg)
            session.flush()
            return msg

        gone1 = _msg("gone-1")      # only in INBOX -> deleted + event
        gone2 = _msg("gone-2")      # INBOX + Archive -> location removed, kept
        keep1 = _msg("keep-1")      # not deleted -> untouched
        session.add_all([
            MessageLocation(message_id=gone1.id, folder_id=inbox.id, uid=1),
            MessageLocation(message_id=gone2.id, folder_id=inbox.id, uid=2),
            MessageLocation(message_id=gone2.id, folder_id=archive.id, uid=3),
            MessageLocation(message_id=keep1.id, folder_id=inbox.id, uid=4),
        ])
        session.commit()
        account_id, folder_id = acc.id, inbox.id
        gone1_id, gone2_id, keep1_id = gone1.id, gone2.id, keep1.id

    monkeypatch.setattr(reconcile_mod, "build_provider", lambda *a, **kw: _StubProvider())
    result = reconcile_folder(account_id, folder_id, worker_id="w-b5b", store=store)

    assert result == {"status": "ok", "deleted": 1, "actions": 4}
    with Session() as session:
        assert session.get(Message, gone1_id) is None
        assert session.get(Message, gone2_id) is not None
        assert session.get(Message, keep1_id) is not None
        remaining_locations = {
            (loc.message_id, loc.folder_id)
            for loc in session.scalars(select(MessageLocation)).all()
            if loc.message_id in (gone1_id, gone2_id, keep1_id)
        }
        assert remaining_locations == {(gone2_id, session.scalar(
            select(Folder.id).where(Folder.account_id == account_id, Folder.remote_id == "Archive")
        )), (keep1_id, folder_id)}
        removed_events = [
            e for e in session.scalars(
                select(OutboxEvent).where(
                    OutboxEvent.event_type == OutboxEventType.MESSAGE_REMOVED.value,
                    OutboxEvent.account_id == account_id,
                )
            ).all()
        ]
        assert len(removed_events) == 1
        assert removed_events[0].payload["message_id"] == str(gone1_id)
        assert removed_events[0].payload["remote_id"] == "gone-1"
