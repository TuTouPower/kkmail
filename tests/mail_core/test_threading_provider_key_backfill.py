"""A174: backfilling provider_thread_key onto an existing thread must be
savepoint-protected.

Previously the assignment was only flushed at the end of
assign_thread_for_message, so a concurrent transaction that created a
thread with the same (account_id, provider_thread_key) made the bare
flush raise IntegrityError and fail the whole metadata page. The fix
wraps assignment+flush in begin_nested and, on conflict, reuses the
thread that won the race.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError

from mail_core.threading.rules import assign_thread_for_message


class _Savepoint:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def _existing_thread(*, thread_id=None, provider_thread_key=None):
    thread = MagicMock()
    thread.id = thread_id or uuid.uuid4()
    thread.provider_thread_key = provider_thread_key
    thread.sort_time = None
    return thread


def _message_for(existing):
    msg = MagicMock()
    msg.id = uuid.uuid4()
    msg.account_id = uuid.uuid4()
    msg.internet_message_id = None
    msg.subject = "Test"
    msg.sort_time = None
    msg.thread_id = existing.id
    return msg


def test_backfill_conflict_reuses_winning_thread():
    existing = _existing_thread(provider_thread_key=None)
    winner = _existing_thread(provider_thread_key="key-1")
    msg = _message_for(existing)

    session = MagicMock()
    session.begin_nested = _Savepoint
    session.get.return_value = existing
    # scalar calls: 1) provider-key lookup -> None (falls through to the
    # message's existing thread), 2) conflict re-query -> winner,
    # 3) ThreadMessage membership check -> None (will add).
    session.scalar.side_effect = [None, winner, None]
    # First flush (the backfill inside the savepoint) loses the unique
    # race; the final flush succeeds.
    session.flush.side_effect = [
        IntegrityError("duplicate key", params=None, orig=Exception("dup")),
        None,
    ]

    assignment = assign_thread_for_message(session, message=msg, provider_thread_key="key-1")

    assert assignment.thread_id == winner.id
    assert msg.thread_id == winner.id


def test_backfill_conflict_without_winner_reraises():
    existing = _existing_thread(provider_thread_key=None)
    msg = _message_for(existing)

    session = MagicMock()
    session.begin_nested = _Savepoint
    session.get.return_value = existing
    session.scalar.side_effect = [None, None]
    session.flush.side_effect = IntegrityError("duplicate key", params=None, orig=Exception("dup"))

    with pytest.raises(IntegrityError):
        assign_thread_for_message(session, message=msg, provider_thread_key="key-1")


def test_backfill_without_conflict_keeps_existing_thread():
    existing = _existing_thread(provider_thread_key=None)
    msg = _message_for(existing)

    session = MagicMock()
    session.begin_nested = _Savepoint
    session.get.return_value = existing
    session.scalar.side_effect = [None, None]
    session.flush.return_value = None

    assignment = assign_thread_for_message(session, message=msg, provider_thread_key="key-1")

    assert assignment.thread_id == existing.id
    assert existing.provider_thread_key == "key-1"
