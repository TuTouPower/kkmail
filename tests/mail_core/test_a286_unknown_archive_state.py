"""A286: sync_message_body must not leak a bare ValueError for unknown
archive state strings stored in the DB.

Historical dirty data / a newer version's state value makes
``ArchiveState(state.state)`` raise ValueError; the API layer only maps
``MessageArchiveStateUnavailable`` to 409, so the bare error became a
500. The fix converts it, carrying the raw state value.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mail_core.mail.application import message_details
from mail_core.mail.storage.models import Message


def _run_with_state(monkeypatch, raw_state: str):
    message_id = uuid.uuid4()
    state = SimpleNamespace(
        state=raw_state,
        priority=2,
        retry_count=0,
        last_error=None,
        pause_reason=None,
        claimed_by=None,
        claimed_at=None,
        updated_at=None,
    )
    message = SimpleNamespace(account_id=uuid.uuid4(), remote_id="verified-remote-id")
    session = Mock()
    session.get.side_effect = lambda model, _mid: {Message: message}.get(model)
    session.scalar.side_effect = lambda _stmt: state

    class SessionFactory:
        def __enter__(self):
            return session

        def __exit__(self, *_args):
            return False

    enqueue = Mock()
    monkeypatch.setattr(message_details, "get_session_factory", lambda: SessionFactory)
    monkeypatch.setattr(message_details, "enqueue_job", enqueue)
    return message_id, enqueue, session


def test_unknown_archive_state_becomes_unavailable_with_raw_value(monkeypatch):
    message_id, enqueue, session = _run_with_state(monkeypatch, "some_future_state")
    with pytest.raises(message_details.MessageArchiveStateUnavailable) as excinfo:
        message_details.sync_message_body(message_id)
    # Must be the domain error (not the bare Enum ValueError) and carry
    # the offending raw value for diagnosis.
    assert type(excinfo.value) is message_details.MessageArchiveStateUnavailable
    assert "some_future_state" in str(excinfo.value)
    enqueue.assert_not_called()
    session.commit.assert_not_called()


def test_empty_archive_state_becomes_unavailable(monkeypatch):
    message_id, enqueue, _session = _run_with_state(monkeypatch, "")
    with pytest.raises(message_details.MessageArchiveStateUnavailable):
        message_details.sync_message_body(message_id)
    enqueue.assert_not_called()
