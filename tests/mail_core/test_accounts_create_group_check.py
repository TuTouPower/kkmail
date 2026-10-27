"""A77: create_account must reject a nonexistent group_id with LookupError."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from mail_core.accounts.service import create_account


class _FakeSession:
    def __init__(self, group_exists: bool):
        self._group_exists = group_exists
        self.added = []

    def execute(self, _stmt):
        return None

    def get(self, model, pk):
        if model.__name__ == "AccountGroup":
            return SimpleNamespace(id=pk) if self._group_exists else None
        return None

    def scalar(self, stmt):
        text = str(stmt).lower()
        if "account_groups" in text:
            return SimpleNamespace(id=uuid.uuid4()) if self._group_exists else None
        return None  # max(master_order) / max(group_order)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass


def test_create_account_rejects_unknown_group_before_insert():
    session = _FakeSession(group_exists=False)
    with pytest.raises(LookupError, match="group not found"):
        create_account(
            session,
            email="user@example.com",
            provider="memory",
            group_id=uuid.uuid4(),
        )
    assert session.added == []


def test_create_account_accepts_existing_group():
    group_id = uuid.uuid4()
    session = _FakeSession(group_exists=True)
    acc = create_account(session, email="user@example.com", provider="memory", group_id=group_id)
    assert acc.group_id == group_id
    assert session.added == [acc]
