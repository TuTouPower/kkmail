"""Flag deltas must patch flags only — never wipe subject/from via stub meta."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.storage import Account, Folder, Message
from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta
from mail_core.sync import acquire_lease, apply_delta_page

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


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
