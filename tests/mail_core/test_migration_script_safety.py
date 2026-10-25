import importlib.util
from pathlib import Path
from types import SimpleNamespace


def test_message_fts_downgrade_does_not_drop_dependents(monkeypatch):
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "src/mail_core/db/alembic/versions/20261021_0003_message_fts.py"
    )
    spec = importlib.util.spec_from_file_location("migration_20261021_0003", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = []
    monkeypatch.setattr(migration, "op", SimpleNamespace(execute=statements.append))

    migration.downgrade()

    assert len(statements) == 1
    assert str(statements[0]).upper() == "DROP TABLE IF EXISTS MESSAGE_SEARCH"
