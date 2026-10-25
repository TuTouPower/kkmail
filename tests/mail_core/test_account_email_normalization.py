from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from mail_core.accounts.service import create_account
from mail_core.mail.storage.models import Account


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "src/mail_core/db/alembic/versions/20261025_0021_account_email_lower_unique.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_20261025_0021", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_account_creation_normalizes_email_before_persistence(monkeypatch):
    import mail_core.accounts.connection as connection

    monkeypatch.setattr(connection, "validate_connection", lambda *_args, **_kwargs: None)

    class Session:
        def __init__(self):
            self.added = []

        def execute(self, _statement):
            return None

        def scalar(self, _statement):
            return None

        def add(self, account):
            self.added.append(account)

        def flush(self):
            return None

    session = Session()
    account = create_account(
        session,
        email="  Karson.Example@Example.COM  ",
        provider="imap",
    )

    assert account.email == "karson.example@example.com"
    assert session.added == [account]


def test_email_migration_is_the_single_linear_head():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory(str(MIGRATION_PATH.parent.parent))

    assert script.get_heads() == ["20261025_0021"]
    assert script.get_revision("20261025_0021").down_revision == "20261025_0020"


def test_account_metadata_has_unique_lower_email_index():
    index = next(index for index in Account.__table__.indexes if index.name == "uq_accounts_email_lower")

    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert ddl == "CREATE UNIQUE INDEX uq_accounts_email_lower ON accounts (lower(email))"


class _Connection:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None

    def execute(self, statement):
        self.statement = str(statement)
        return SimpleNamespace(fetchall=lambda: self.rows)


def test_email_migration_aborts_on_case_insensitive_duplicates_without_creating_index(monkeypatch):
    migration = _load_migration()
    connection = _Connection([(["account-1", "account-2"],)])
    create_index = Mock()
    monkeypatch.setattr(
        migration,
        "op",
        SimpleNamespace(get_bind=lambda: connection, create_index=create_index),
    )

    with pytest.raises(RuntimeError, match="per-account resolution") as exc_info:
        migration.upgrade()

    assert "account-1" in str(exc_info.value)
    assert "account-2" in str(exc_info.value)
    assert "GROUP BY lower(email)" in connection.statement
    assert "HAVING count(*) > 1" in connection.statement
    create_index.assert_not_called()


def test_email_migration_creates_unique_expression_index_when_no_conflicts(monkeypatch):
    migration = _load_migration()
    connection = _Connection([])
    create_index = Mock()
    monkeypatch.setattr(
        migration,
        "op",
        SimpleNamespace(get_bind=lambda: connection, create_index=create_index),
    )

    migration.upgrade()

    create_index.assert_called_once()
    args, kwargs = create_index.call_args
    assert args[:2] == ("uq_accounts_email_lower", "accounts")
    assert str(args[2][0]) == "lower(email)"
    assert kwargs == {"unique": True}
