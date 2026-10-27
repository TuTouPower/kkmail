"""A232: list_accounts must not compute discarded counts on grouped queries."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from mail_core.accounts.service import list_accounts


class _FakeSession:
    def __init__(self):
        self.scalar_calls = []

    def scalar(self, stmt):
        text = str(stmt).lower()
        self.scalar_calls.append(text)
        grouped = "accounts.group_id" in text
        manual_probe = "group_order" in text or "master_order" in text
        if manual_probe:
            return 0
        return 7 if grouped else 99

    def scalars(self, _stmt):
        return SimpleNamespace(all=lambda: [])


def test_list_accounts_grouped_computes_each_count_once():
    session = _FakeSession()
    accounts, total = list_accounts(session, group_id=uuid.uuid4())
    assert accounts == []
    assert total == 7  # the grouped count, not the discarded full-table count
    # exactly two scalar probes: grouped total + grouped manual-order probe
    assert len(session.scalar_calls) == 2
    assert all("accounts.group_id" in call for call in session.scalar_calls)


def test_list_accounts_ungrouped_counts_once_each():
    session = _FakeSession()
    accounts, total = list_accounts(session)
    assert accounts == []
    assert total == 99
    assert len(session.scalar_calls) == 2
