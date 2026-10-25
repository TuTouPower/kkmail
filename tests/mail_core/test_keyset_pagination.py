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


def test_decode_rejects_malformed_cursor():
    with pytest.raises(InvalidCursor):
        decode_cursor("not-base64!!!")
    bad = base64.urlsafe_b64encode(b"2026-01-01T00:00:00+00:00|").decode().rstrip("=")
    with pytest.raises(InvalidCursor):
        decode_cursor(bad)
    bad3 = base64.urlsafe_b64encode(b"only-time-no-pipe").decode().rstrip("=")
    with pytest.raises(InvalidCursor):
        decode_cursor(bad3)
    bad4 = base64.urlsafe_b64encode(b"|not-a-uuid").decode().rstrip("=")
    with pytest.raises(InvalidCursor):
        decode_cursor(bad4)


def test_encode_decode_roundtrip():
    mid = uuid.uuid4()
    st = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    token = encode_cursor(st, mid)
    got_st, got_id = decode_cursor(token)
    assert got_id == mid
    assert got_st == st


def test_encode_decode_nullable_cursor_roundtrip():
    mid = uuid.uuid4()
    token = encode_cursor(None, mid)

    got_st, got_id = decode_cursor(token)

    assert got_st is None
    assert got_id == mid


def test_sort_order_validation():
    with pytest.raises(ValueError, match="sort_order"):
        list_messages_keyset(None, folder_ids=[], sort_order="invalid")


def test_preferred_folder_selection_compiles_without_database():
    from sqlalchemy.dialects import postgresql

    class EmptyResult:
        def all(self):
            return []

    class CaptureSession:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return EmptyResult()

    preferred_folder_id = uuid.uuid4()
    session = CaptureSession()
    list_messages_keyset(
        session,
        folder_ids=[uuid.uuid4(), preferred_folder_id],
        preferred_folder_id=preferred_folder_id,
    )

    compiled = session.statement.compile(dialect=postgresql.dialect())
    assert "coalesce" in str(compiled).lower()
    assert "case when" in str(compiled).lower()
    scalar_uuids = [value for value in compiled.params.values() if isinstance(value, uuid.UUID)]
    assert preferred_folder_id in scalar_uuids


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

        # Ascending sort: starts from oldest (m0)
        page_asc1 = list_messages_keyset(session, folder_ids=[folder_id], limit=2, sort_order="asc")
        assert [i.subject for i in page_asc1.items] == ["m0", "m1"]
        assert page_asc1.next_cursor

        page_asc2 = list_messages_keyset(session, folder_ids=[folder_id], limit=2, cursor=page_asc1.next_cursor, sort_order="asc")
        assert [i.subject for i in page_asc2.items] == ["m2", "m3"]
        assert page_asc2.next_cursor

        page_asc3 = list_messages_keyset(session, folder_ids=[folder_id], limit=2, cursor=page_asc2.next_cursor, sort_order="asc")
        assert [i.subject for i in page_asc3.items] == ["m4"]
        assert page_asc3.next_cursor is None


@pytestmark_db
@pytest.mark.parametrize(
    ("sort_order", "expected_ids"),
    [
        ("asc", [1, 2, 3, 4, 5]),
        ("desc", [3, 2, 1, 5, 4]),
    ],
)
def test_nullable_sort_time_pages_with_unknown_dates_last(sort_order, expected_ids):
    from mail_core.accounts import create_account
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import Folder, Message, MessageLocation

    Session = get_session_factory()
    base = datetime(2026, 6, 1, tzinfo=timezone.utc)
    message_ids = [uuid.UUID(int=value) for value in range(1, 6)]
    with Session() as session:
        acc = create_account(session, email=f"nullable-keyset-{uuid.uuid4().hex[:8]}@ex.com", provider="stub")
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        times = [base, base + timedelta(minutes=1), base + timedelta(minutes=1), None, None]
        for index, (message_id, sort_time) in enumerate(zip(message_ids, times), start=1):
            message = Message(
                id=message_id,
                account_id=acc.id,
                remote_id=f"nullable-{index}",
                subject=f"m{index}",
                from_address="a@b.c",
                sort_time=sort_time,
            )
            session.add(message)
            session.flush()
            session.add(MessageLocation(message_id=message.id, folder_id=folder.id, uid=index))
        session.commit()
        folder_id = folder.id

    with Session() as session:
        cursor = None
        actual_ids = []
        while True:
            page = list_messages_keyset(
                session,
                folder_ids=[folder_id],
                limit=2,
                cursor=cursor,
                sort_order=sort_order,
            )
            actual_ids.extend(message.id for message in page.items)
            cursor = page.next_cursor
            if cursor is None:
                break

    assert actual_ids == [message_ids[value - 1] for value in expected_ids]
