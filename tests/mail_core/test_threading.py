from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from mail_core.accounts import create_account
from mail_core.db.session import get_session_factory
from mail_core.mail.storage import Message, ThreadMessage
from mail_core.threading import (
    assign_thread_for_message,
    extract_message_ids,
    normalize_message_id,
    normalize_subject,
)

_requires_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_normalize_and_extract_ids():
    assert normalize_message_id("foo@bar.com") == "<foo@bar.com>"
    assert normalize_message_id("<a@b.c>") == "<a@b.c>"
    assert extract_message_ids("<a@b.c> <c@d.e>", "Re: x") == ["<a@b.c>", "<c@d.e>"]
    assert normalize_subject("Re: Fwd: Hello") == "hello"


@_requires_db
def test_in_reply_to_links_and_creates_parent_thread():
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc = create_account(session, email=f"th-{uuid.uuid4().hex[:8]}@ex.com", provider="imap")
        parent = Message(
            account_id=acc.id,
            remote_id="p1",
            subject="Root",
            from_address="a@ex.com",
            sort_time=now,
            internet_message_id="<root@ex.com>",
        )
        session.add(parent)
        session.flush()
        # parent has no thread yet
        child = Message(
            account_id=acc.id,
            remote_id="c1",
            subject="Re: Root",
            from_address="b@ex.com",
            sort_time=now,
            internet_message_id="<child@ex.com>",
        )
        session.add(child)
        session.flush()
        result = assign_thread_for_message(
            session,
            message=child,
            in_reply_to="<root@ex.com>",
        )
        assert result.linked_via == "in_reply_to"
        assert result.created is False  # thread created via parent ensure, assignment says created on new only
        session.refresh(parent)
        session.refresh(child)
        assert parent.thread_id == child.thread_id == result.thread_id
        members = session.scalars(
            select(ThreadMessage.message_id).where(ThreadMessage.thread_id == result.thread_id)
        ).all()
        assert set(members) == {parent.id, child.id}
        session.commit()


@_requires_db
def test_references_walks_newest_first():
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc = create_account(session, email=f"th2-{uuid.uuid4().hex[:8]}@ex.com", provider="imap")
        mid_msg = Message(
            account_id=acc.id,
            remote_id="m",
            subject="Mid",
            from_address="a@ex.com",
            sort_time=now,
            internet_message_id="<mid@ex.com>",
        )
        session.add(mid_msg)
        session.flush()
        assign_thread_for_message(session, message=mid_msg)
        session.flush()
        leaf = Message(
            account_id=acc.id,
            remote_id="l",
            subject="Re: Mid",
            from_address="b@ex.com",
            sort_time=now,
            internet_message_id="<leaf@ex.com>",
        )
        session.add(leaf)
        session.flush()
        # Unknown ancestor first, mid last in References string (RFC: oldest → newest)
        result = assign_thread_for_message(
            session,
            message=leaf,
            references="<missing@ex.com> <mid@ex.com>",
        )
        assert result.linked_via == "references"
        session.refresh(leaf)
        session.refresh(mid_msg)
        assert leaf.thread_id == mid_msg.thread_id
        session.commit()


@_requires_db
def test_provider_thread_key():
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc = create_account(session, email=f"th3-{uuid.uuid4().hex[:8]}@ex.com", provider="gmail")
        a = Message(account_id=acc.id, remote_id="1", subject="A", from_address="a@ex.com", sort_time=now)
        b = Message(account_id=acc.id, remote_id="2", subject="B", from_address="a@ex.com", sort_time=now)
        session.add_all([a, b])
        session.flush()
        r1 = assign_thread_for_message(session, message=a, provider_thread_key="thread-9")
        r2 = assign_thread_for_message(session, message=b, provider_thread_key="thread-9")
        assert r1.thread_id == r2.thread_id
        assert r2.linked_via == "provider_key"
        assert r2.created is False
        session.commit()
