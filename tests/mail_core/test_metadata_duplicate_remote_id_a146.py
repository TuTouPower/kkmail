"""A146: a metadata page repeating a remote_id must not create two
Message rows / two MessageLocation rows for it.

upsert_messages only registered *pre-existing* messages in the locs map;
a message created for the first occurrence was invisible to the second
occurrence in the same page, which added a second MessageLocation and hit
the (message_id, folder_id) unique constraint, poisoning the whole page.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

import mail_core.sync.metadata as metadata_mod
from mail_core.mail.storage.models import Message, MessageLocation
from mail_core.providers.base import RemoteMessageMeta


class _FakeSession:
    def __init__(self, existing_messages=()):
        self._existing = list(existing_messages)
        self.added: list = []
        self._scalars_calls = 0

    def scalars(self, _stmt):
        self._scalars_calls += 1
        if self._scalars_calls == 1:
            return iter(self._existing)
        return iter([])  # no pre-existing locations

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass


def _meta(remote_id: str, subject: str) -> RemoteMessageMeta:
    return RemoteMessageMeta(
        remote_id=remote_id,
        subject=subject,
        from_address="a@b.c",
        from_name=None,
        sort_time=datetime.now(timezone.utc),
        is_read=False,
        has_attachments=False,
        uid=101,
    )


@pytest.fixture(autouse=True)
def _no_intents(monkeypatch):
    monkeypatch.setattr(
        "mail_core.sync.remote_push.get_unconverged_field_intents",
        lambda *args, **kwargs: {},
    )


def test_duplicate_remote_id_in_one_page_creates_one_message_and_location():
    session = _FakeSession()
    metas = [_meta("101", "First"), _meta("101", "Duplicate"), _meta("102", "Other")]
    outcomes = metadata_mod.upsert_messages(
        session, account_id=uuid.uuid4(), folder_id=uuid.uuid4(), metas=metas
    )
    messages = [o for o in session.added if isinstance(o, Message)]
    locations = [o for o in session.added if isinstance(o, MessageLocation)]
    assert len(messages) == 2
    assert len(locations) == 2
    assert len(outcomes) == 2
    # First occurrence wins for the duplicated remote_id.
    subjects = {o.message.remote_id: o.message.subject for o in outcomes}
    assert subjects["101"] == "First"


def test_duplicate_remote_id_for_existing_message_creates_one_location():
    account_id = uuid.uuid4()
    existing = Message(
        id=uuid.uuid4(),
        account_id=account_id,
        remote_id="201",
        sort_time=datetime.now(timezone.utc),
    )
    session = _FakeSession(existing_messages=[existing])
    metas = [_meta("201", "S"), _meta("201", "S")]
    outcomes = metadata_mod.upsert_messages(
        session, account_id=account_id, folder_id=uuid.uuid4(), metas=metas
    )
    locations = [o for o in session.added if isinstance(o, MessageLocation)]
    assert len(locations) == 1
    assert len(outcomes) == 1
