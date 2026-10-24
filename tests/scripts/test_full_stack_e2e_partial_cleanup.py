"""Full-stack E2E setup must clean resources after partial DB allocation."""

from contextlib import contextmanager
import importlib.util
import os
from pathlib import Path
import secrets

import pytest
import sqlalchemy


def _load_runner():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts/run_full_stack_e2e.py"
    spec = importlib.util.spec_from_file_location("run_full_stack_e2e", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_partial_database_creation_is_cleaned_after_setup_failure(tmp_path, monkeypatch):
    module = _load_runner()
    module.ROOT = tmp_path
    monkeypatch.setattr(module, "load_env_test", lambda: None)

    class ConnectedSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(module.socket, "create_connection", lambda *_args, **_kwargs: ConnectedSocket())
    monkeypatch.setenv("KKMAIL_TEST_PG_PASSWORD", secrets.token_urlsafe(32))

    statements = []
    created_urls = []
    original_url_create = sqlalchemy.engine.URL.create

    def record_url_create(*args, **kwargs):
        url = original_url_create(*args, **kwargs)
        created_urls.append(url)
        return url

    monkeypatch.setattr(
        sqlalchemy.engine.URL,
        "create",
        staticmethod(record_url_create),
    )

    class FakeConnection:
        def execute(self, statement):
            sql = str(statement)
            statements.append(sql)
            if sql.startswith('CREATE DATABASE '):
                raise RuntimeError("simulated database creation failure")

    class FakeEngine:
        disposed = False

        @contextmanager
        def connect(self):
            yield FakeConnection()

        def dispose(self):
            self.disposed = True

    engine = FakeEngine()
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *_args, **_kwargs: engine)

    with pytest.raises(RuntimeError, match="simulated database creation failure"):
        module.main()

    assert any(
        statement.startswith("CREATE ROLE ") and " LOGIN PASSWORD " in statement
        for statement in statements
    )
    assert any(statement.startswith("CREATE DATABASE ") for statement in statements)
    assert any(statement.startswith("DROP DATABASE IF EXISTS ") for statement in statements)
    assert any(statement.startswith("DROP ROLE IF EXISTS ") for statement in statements)
    assert created_urls[0].username == "postgres"
    assert created_urls[1].username.startswith("kkmail_e2e_owner_")
    assert created_urls[1].password != created_urls[0].password
    assert engine.disposed
