from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "src/mail_core/db/alembic/versions/20261021_0013_auth_credentials_session_epoch.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("auth_credentials_session_epoch", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_downgrade_rejects_null_login_hash_before_schema_changes():
    migration = _load_migration()
    connection = Mock()
    connection.execute.return_value.scalar_one.return_value = True

    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration.op, "alter_column") as alter_column,
        patch.object(migration.op, "drop_column") as drop_column,
    ):
        with pytest.raises(
            RuntimeError,
            match="auth_credentials.login_password_hash contains NULL values",
        ):
            migration.downgrade()

    alter_column.assert_not_called()
    drop_column.assert_not_called()


def test_downgrade_proceeds_when_all_login_hashes_are_present():
    migration = _load_migration()
    connection = Mock()
    connection.execute.return_value.scalar_one.return_value = False

    with (
        patch.object(migration.op, "get_bind", return_value=connection),
        patch.object(migration.op, "alter_column") as alter_column,
        patch.object(migration.op, "drop_column") as drop_column,
    ):
        migration.downgrade()

    alter_column.assert_called_once()
    drop_column.assert_called_once_with("auth_credentials", "session_epoch")
