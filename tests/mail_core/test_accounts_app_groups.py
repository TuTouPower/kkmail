from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from mail_core.mail.application import accounts as accounts_app


def test_rename_group_counts_members_in_sql(monkeypatch):
    group_id = uuid4()
    group = SimpleNamespace(id=group_id, name="Renamed", color=None, sort_order=0)
    session = MagicMock()
    session.scalar.return_value = 3
    context = MagicMock()
    context.__enter__.return_value = session
    monkeypatch.setattr(accounts_app, "get_session_factory", lambda: lambda: context)
    monkeypatch.setattr(accounts_app, "rename_group", lambda *_args, **_kwargs: group)

    result = accounts_app.rename_group_app(group_id, name="Renamed")

    statement = str(session.scalar.call_args.args[0]).lower()
    assert "count(" in statement
    assert "accounts.group_id" in statement
    assert result.account_count == 3


def test_account_dto_group_map_selects_groups_without_count_join():
    group = SimpleNamespace(id=uuid4(), name="Group", color="blue")
    session = MagicMock()
    session.scalars.return_value.all.return_value = [group]

    groups = accounts_app._groups_by_id(session)

    statement = str(session.scalars.call_args.args[0]).lower()
    assert groups == {group.id: group}
    assert "account_groups" in statement
    assert "join" not in statement
    assert "count(" not in statement
