"""A287: messages_by_ids folder_id must be deterministic.

Pre-fix, ``folder_id`` came from ``setdefault`` over an outer join
with MessageLocation: a message present in several folders produced
one join row per location and the first row the database happened to
return won. The item's folder_id is now the first entry of the
``locations`` list, which is loaded with a defined order
(message_id, Folder.id), so the primary folder is stable.
"""

from __future__ import annotations

import uuid

from mail_core.mail.application.queries import messages_by_ids
from mail_core.mail.storage.models import Message

_LOW = uuid.UUID(int=1)
_HIGH = uuid.UUID(int=2)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Serves canned execute() results in call order."""

    def __init__(self, results):
        self._results = list(results)

    def execute(self, _stmt):
        return _Result(self._results.pop(0))


def _message(mid: uuid.UUID) -> Message:
    return Message(
        id=mid,
        account_id=uuid.uuid4(),
        subject="s",
        from_address="a@b.c",
        from_name=None,
        sort_time=None,
        is_read=False,
        is_flagged=False,
        has_attachments=False,
        snippet="preview",  # non-empty: body previews are skipped
    )


def test_folder_id_is_first_location_in_defined_order_not_first_join_row():
    mid = uuid.uuid4()
    msg = _message(mid)
    # Adversarial join order: the high folder id's row comes first.
    join_rows = [(msg, _HIGH), (msg, _LOW)]
    # _folder_locations_by_message_ids orders by Folder.id ascending.
    location_rows = [(mid, _LOW, "inbox"), (mid, _HIGH, "all")]
    session = _FakeSession([join_rows, location_rows])

    items = messages_by_ids(session, [mid])

    assert len(items) == 1
    assert items[0].folder_id == _LOW
    assert [loc.folder_id for loc in items[0].locations] == [_LOW, _HIGH]


def test_message_without_locations_has_no_folder_id():
    mid = uuid.uuid4()
    msg = _message(mid)
    session = _FakeSession([[(msg, None)], []])

    items = messages_by_ids(session, [mid])

    assert len(items) == 1
    assert items[0].folder_id is None
    assert items[0].locations == []
