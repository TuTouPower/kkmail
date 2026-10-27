"""A314: get_sidebar_layout must use two simple queries, not a FULL OUTER JOIN."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from mail_core.accounts.service import get_sidebar_layout


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, groups, accounts):
        self._groups = groups
        self._accounts = accounts
        self.scalars_calls = []

    def execute(self, _stmt):
        raise AssertionError("get_sidebar_layout must not run a join query")

    def scalars(self, stmt):
        text = str(stmt).lower()
        self.scalars_calls.append(text)
        if "account_groups" in text:
            return _Result(list(self._groups))
        return _Result(list(self._accounts))


def test_get_sidebar_layout_assembles_from_two_simple_queries():
    g1 = SimpleNamespace(id=uuid.uuid4(), name="B group", sort_order=1)
    g2 = SimpleNamespace(id=uuid.uuid4(), name="A group", sort_order=0)
    a1 = SimpleNamespace(
        id=uuid.uuid4(), email="one@example.com", group_id=g1.id, master_order=1, group_order=0
    )
    a2 = SimpleNamespace(
        id=uuid.uuid4(), email="two@example.com", group_id=None, master_order=0, group_order=None
    )
    a3 = SimpleNamespace(
        id=uuid.uuid4(), email="three@example.com", group_id=g1.id, master_order=2, group_order=1
    )
    session = _FakeSession([g1, g2], [a1, a2, a3])

    layout = get_sidebar_layout(session)

    assert len(session.scalars_calls) == 2
    assert layout["group_ids"] == [g2.id, g1.id]  # by sort_order
    assert layout["master_account_ids"] == [a2.id, a1.id, a3.id]
    assert layout["ungrouped_account_ids"] == [a2.id]
    assert layout["group_account_ids"] == {g2.id: [], g1.id: [a1.id, a3.id]}
    assert isinstance(layout["revision"], str) and layout["revision"]
