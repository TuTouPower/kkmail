"""A317: get_message_detail attachments follow MIME part order.

Pre-fix the query ordered attachments by filename, so the reader
showed parts in alphabetical rather than MIME order (and "10" sorted
before "2" even by name-like keys). Attachments are now sorted by the
numeric ordinal carried in part_id — ``str(part_index)`` from the
MIME walk, or the ``legacy_<n>`` suffix backfilled by migration 0015 —
with filename only as the tiebreak; rows without a part ordinal sort
last by filename.
"""

from __future__ import annotations

import uuid

from mail_core.mail.application.queries import get_message_detail
from mail_core.mail.storage.models import Attachment, Message


class _Scalars:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


class _FakeSession:
    def __init__(self, message, attachments):
        self._message = message
        self._attachments = attachments

    def get(self, model, _id):
        if model is Message:
            return self._message
        return None  # MessageBody: no parsed body needed for ordering

    def scalars(self, _stmt):
        return _Scalars(self._attachments)


def _message(mid: uuid.UUID) -> Message:
    return Message(
        id=mid,
        account_id=uuid.uuid4(),
        subject="s",
        from_address="a@b.c",
        from_name=None,
        to_addresses=[],
        cc_addresses=[],
        sort_time=None,
        is_read=False,
        is_flagged=False,
        has_attachments=True,
        snippet="x",
    )


def _attachment(mid: uuid.UUID, part_id, filename: str) -> Attachment:
    return Attachment(
        id=uuid.uuid4(),
        message_id=mid,
        part_id=part_id,
        filename=filename,
        content_type="text/plain",
        size_bytes=1,
        is_inline=False,
    )


def test_attachments_sorted_by_numeric_part_id_not_filename():
    mid = uuid.uuid4()
    # Filename order would be a(2), m(10), z(1); scrambled input order
    # simulates an unordered database return.
    atts = [
        _attachment(mid, "10", "m.txt"),
        _attachment(mid, "2", "a.txt"),
        _attachment(mid, "1", "z.txt"),
    ]
    detail = get_message_detail(_FakeSession(_message(mid), atts), mid)
    assert detail is not None
    assert [a.filename for a in detail.attachments] == ["z.txt", "a.txt", "m.txt"]


def test_legacy_part_ids_use_their_numeric_suffix_and_missing_part_id_sorts_last():
    mid = uuid.uuid4()
    atts = [
        _attachment(mid, None, "b-nopart.txt"),
        _attachment(mid, "legacy_10", "l10.txt"),
        _attachment(mid, "legacy_2", "l2.txt"),
    ]
    detail = get_message_detail(_FakeSession(_message(mid), atts), mid)
    assert detail is not None
    assert [a.filename for a in detail.attachments] == ["l2.txt", "l10.txt", "b-nopart.txt"]
