"""Lifecycle probes against the explicitly configured dedicated test instance."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

PATH = Path(__file__).resolve().parents[2] / "scripts" / "test_pg_runtime.py"
spec = importlib.util.spec_from_file_location("test_pg_runtime_live", PATH)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

pytestmark = pytest.mark.skipif(os.environ.get("KKMAIL_TEST_MODE") == "unit" or not os.environ.get("KKMAIL_TEST_PG_PASSWORD"),
                                reason="dedicated runtime probes require explicit test credentials")


def test_concurrent_runs_and_exact_cleanup_reuse_service():
    original_instance = runtime.instance()
    with runtime.engine(runtime.admin_url(original_instance[1])).connect() as connection:
        started_at = connection.scalar(text("SELECT pg_postmaster_start_time()"))
    with ThreadPoolExecutor(max_workers=2) as executor:
        runs = list(executor.map(lambda _: runtime.create_run(), range(2)))
    try:
        assert runs[0][0] != runs[1][0]
        assert runs[0][1]["database"] != runs[1][1]["database"]
        for i, (_, record) in enumerate(runs):
            url = runtime.admin_url(record["port"]).set(database=record["database"])
            with runtime.engine(url).begin() as connection:
                if i == 0:
                    connection.execute(text("CREATE TABLE sentinel(value integer)"))
                    connection.execute(text("INSERT INTO sentinel VALUES (42)"))
                else:
                    assert connection.scalar(text("SELECT to_regclass('public.sentinel')")) is None
        runtime.cleanup(runs[0][0])
        second = runs[1][1]
        with runtime.engine(runtime.admin_url(second["port"]).set(database=second["database"])).connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
            assert connection.scalar(text("SELECT pg_postmaster_start_time()")) == started_at
        assert runtime.instance() == original_instance
    finally:
        for directory, _ in runs:
            runtime.cleanup(directory)


def test_direct_pytest_and_cleanup_reject_unowned_sentinel(tmp_path):
    directory, record = runtime.create_run()
    url = runtime.admin_url(record["port"]).set(database=record["database"])
    try:
        with runtime.engine(url).begin() as connection:
            connection.execute(text("CREATE TABLE sentinel(value integer)"))
            connection.execute(text("INSERT INTO sentinel VALUES (42)"))
        with runtime.engine(runtime.admin_url(record["port"])).connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'COMMENT ON DATABASE "{record["database"]}" IS \'unowned-sentinel\''))
        env = os.environ.copy()
        env.update(MAIL_CORE_DATABASE_URL=url.render_as_string(hide_password=False),
                   KKMAIL_TEST_RUN_DIR=str(directory), TMPDIR=str(tmp_path))
        result = subprocess.run([sys.executable, "-m", "pytest", "tests/mail_core/test_schema_pg.py", "--collect-only", "-q"],
                                cwd=runtime.ROOT, env=env, capture_output=True, text=True)
        assert result.returncode != 0
        assert "ownership marker mismatch" in result.stderr
        assert runtime.password() not in result.stdout + result.stderr
        with pytest.raises(runtime.SafetyError, match="ownership marker mismatch"):
            runtime.cleanup(directory)
        with runtime.engine(url).connect() as connection:
            assert connection.scalar(text("SELECT value FROM sentinel")) == 42
    finally:
        with runtime.engine(runtime.admin_url(record["port"])).connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'COMMENT ON DATABASE "{record["database"]}" IS \'{record["marker"]}\''))
        runtime.cleanup(directory)


def test_real_migration_failure_cleans_database(monkeypatch):
    created = []
    original_create = runtime.create_run
    original_child = runtime.child

    def capture_run():
        result = original_create()
        created.append(result[0])
        return result

    def broken_revision(command, env):
        with runtime.engine(env["MAIL_CORE_DATABASE_URL"]).begin() as connection:
            connection.execute(text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"))
            connection.execute(text("INSERT INTO alembic_version VALUES ('missing_test_revision')"))
        return original_child(command, env)

    monkeypatch.setattr(runtime, "child", broken_revision)
    monkeypatch.setattr(runtime, "create_run", capture_run)
    with pytest.raises(runtime.TestFailure):
        runtime.run([])
    assert len(created) == 1
    record = runtime.load_record(created.pop())
    assert record["state"] == "cleaned"
    with runtime.engine(runtime.admin_url(record["port"])).connect() as connection:
        assert connection.scalar(text("SELECT 1 FROM pg_database WHERE datname=:db"), {"db": record["database"]}) is None


@pytest.mark.parametrize("error", [OSError("record write failed"), KeyboardInterrupt()])
def test_allocation_failure_cleans_owned_database(monkeypatch, error):
    original_write = runtime.write_record
    directories = []

    def fail_running_write(directory, record):
        if record["state"] == "running":
            directories.append(directory)
            raise error
        return original_write(directory, record)

    monkeypatch.setattr(runtime, "write_record", fail_running_write)
    with pytest.raises(type(error)):
        runtime.create_run()
    record = runtime.load_record(directories[0])
    assert record["state"] == "cleaned"
    with runtime.engine(runtime.admin_url(record["port"])).connect() as connection:
        assert connection.scalar(text("SELECT 1 FROM pg_database WHERE datname=:db"), {"db": record["database"]}) is None
        assert connection.scalar(text("SELECT 1 FROM pg_roles WHERE rolname=:role"), {"role": record["owner_role"]}) is None
