"""A58: cc_addresses must be indexed into to_text so cc recipients are searchable."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from mail_core.mail.storage.models import Message, MessageBody, MessageSearch
from mail_core.search.index import upsert_message_search, upsert_message_search_batch


class _FakeSession:
    def __init__(self, message):
        self._message = message
        self.added = []
        self.new = set()

    def get(self, model, _pk):
        if model is Message:
            return self._message
        if model is MessageBody:
            return None
        if model is MessageSearch:
            return self.added[0] if self.added else None
        return None

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def scalars(self, _stmt):
        return []


def _msg(**overrides):
    base = dict(
        id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        subject="Hello",
        from_name="Sender",
        from_address="sender@example.com",
        to_addresses=[{"name": "To Person", "address": "to@example.com"}],
        cc_addresses=[
            {"name": "Cc Person", "address": "cc@example.com"},
            "plain-cc@example.com",
        ],
        snippet="snippet",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_upsert_message_search_indexes_cc_addresses():
    msg = _msg()
    session = _FakeSession(msg)
    row = upsert_message_search(session, message_id=msg.id, body_text="body")
    assert "to@example.com" in row.to_text
    assert "Cc Person" in row.to_text
    assert "cc@example.com" in row.to_text
    assert "plain-cc@example.com" in row.to_text


def test_upsert_message_search_batch_indexes_cc_addresses():
    msg = _msg()
    session = _FakeSession(msg)
    upsert_message_search_batch(session, messages=[msg])
    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, MessageSearch)
    assert "cc@example.com" in row.to_text
    assert "plain-cc@example.com" in row.to_text
