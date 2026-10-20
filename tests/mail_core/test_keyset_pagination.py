"""Keyset cursor encode/decode and list pagination (opaque token; no partial apply)."""

from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from mail_core.mail.application.queries import (
    InvalidCursor,
    decode_cursor,
    encode_cursor,
    list_messages_keyset,
)

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_decode_rejects_partial_and_malformed():
    with pytest.raises(InvalidCursor):
        decode_cursor("not-base64!!!")
    bad = base64.urlsafe_b64encode(b"2026-01-01T00:00:00+00:00|").decode().rstrip("=")
    with pytest.raises(InvalidCursor):
        decode_cursor(bad)
    bad2 = base64.urlsafe_b64encode(b"|aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee").decode().rstrip("=")
    with pytest.raises(InvalidCursor):
        decode_cursor(bad2)
    bad3 = base64.urlsafe_b64encode(b"only-time-no-pipe").decode().rstrip("=")
    with pytest.raises(InvalidCursor):
        decode_cursor(bad3)


def test_encode_decode_roundtrip():
    mid = uuid.uuid4()
    st = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    token = encode_cursor(st, mid)
    got_st, got_id = decode_cursor(token)
    assert got_id == mid
    assert got_st == st


@pytestmark_db
def test_list_messages_keyset_pages_without_overlap():
    from mail_core.accounts import create_account
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import Folder, Message, MessageLocation

    Session = get_session_factory()
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    with Session() as session:
        acc = create_account(session, email=f"keyset-{uuid.uuid4().hex[:8]}@ex.com", provider="stub")
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        for i in range(5):
            m = Message(
                account_id=acc.id,
                remote_id=f"r-{i}",
                subject=f"m{i}",
                from_address="a@b.c",
                sort_time=base + timedelta(minutes=i),
                is_read=False,
                is_flagged=False,
                has_attachments=False,
            )
            session.add(m)
            session.flush()
            session.add(MessageLocation(message_id=m.id, folder_id=folder.id, uid=i + 1))
        session.commit()
        folder_id = folder.id

    with Session() as session:
        page1 = list_messages_keyset(session, folder_ids=[folder_id], limit=2)
        assert len(page1.items) == 2
        assert page1.next_cursor
        assert page1.items[0].subject == "m4"
        assert page1.items[1].subject == "m3"

        page2 = list_messages_keyset(session, folder_ids=[folder_id], limit=2, cursor=page1.next_cursor)
        assert [i.subject for i in page2.items] == ["m2", "m1"]
        assert page2.next_cursor

        page3 = list_messages_keyset(session, folder_ids=[folder_id], limit=2, cursor=page2.next_cursor)
        assert [i.subject for i in page3.items] == ["m0"]
        assert page3.next_cursor is None

        seen = {i.id for i in page1.items + page2.items + page3.items}
        assert len(seen) == 5
