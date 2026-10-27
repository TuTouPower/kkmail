"""Safety checks must run before connecting or deleting test data."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest


PATH = Path(__file__).resolve().parents[2] / "scripts" / "test_pg_runtime.py"
spec = importlib.util.spec_from_file_location("test_pg_runtime", PATH)
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


@pytest.mark.parametrize("url", [
    "", "sqlite:///kkmail_test_example", "postgresql://u:p@127.0.0.1/business",
    "postgresql://u:p@remote/kkmail_test_" + "a" * 32,
    "postgresql://u:p@127.0.0.1/kkmail_test_" + "a" * 32 + "?dbname=business",
    "postgresql://u:p@127.0.0.1/kkmail_test_" + "a" * 32 + "?host=remote",
])
def test_reject_unsafe_url_before_connecting(url):
    with pytest.raises(runtime.SafetyError):
        runtime.checked_url(url)


def test_accept_exact_owned_database_shape():
    url = runtime.checked_url("postgresql+psycopg://u:p@127.0.0.1:15433/kkmail_test_" + "a" * 32)
    assert url.database == "kkmail_test_" + "a" * 32


def test_direct_pytest_requires_ownership_even_with_safe_name(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1/kkmail_test_" + "a" * 32)
    monkeypatch.delenv("KKMAIL_TEST_RUN_DIR", raising=False)
    with pytest.raises(runtime.SafetyError, match="ownership"):
        runtime.guard_database()


def test_no_password_fails_without_invoking_docker(monkeypatch):
    monkeypatch.delenv("KKMAIL_TEST_PG_PASSWORD", raising=False)
    monkeypatch.setattr(runtime, "docker", lambda *a, **k: pytest.fail("docker invoked"))
    with pytest.raises(runtime.SafetyError, match="KKMAIL_TEST_PG_PASSWORD"):
        runtime.start()


def test_missing_password_error_hints_env_test(monkeypatch):
    monkeypatch.delenv("KKMAIL_TEST_PG_PASSWORD", raising=False)
    with pytest.raises(runtime.SafetyError, match=r"\.env\.test.*(main|worktree)"):
        runtime.password()


@pytest.mark.parametrize("raw_url", [None, "postgresql://user:must-not-appear@127.0.0.1/business"])
def test_direct_pytest_refuses_before_collection_without_leaking_secrets(raw_url, tmp_path):
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("MAIL_CORE_", "KKMAIL_TEST_"))}
    env["TMPDIR"] = str(tmp_path)
    if raw_url:
        env["MAIL_CORE_DATABASE_URL"] = raw_url
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/mail_core/test_schema_pg.py", "--collect-only", "-q"],
                            cwd=PATH.parents[1], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert "ERROR" in result.stderr
    assert "must-not-appear" not in result.stdout + result.stderr


def test_docker_failure_surfaces_redacted_stderr(monkeypatch):
    from types import SimpleNamespace

    def fake_run(cmd, **kwargs):
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="daemon boom password=hunter2 token: abc123 "
                   "KKMAIL_TEST_PG_PASSWORD=s3cret postgres://u:p4ss@127.0.0.1/db",
        )

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    with pytest.raises(runtime.SafetyError) as excinfo:
        runtime.docker("ps")
    message = str(excinfo.value)
    # stderr 的诊断内容应回显，但凭据赋值与 URL 密码必须脱敏
    assert "daemon boom" in message
    assert "hunter2" not in message
    assert "abc123" not in message
    assert "s3cret" not in message
    assert "p4ss" not in message


def test_required_pg_skip_is_failure_report_not_internal_error(tmp_path):
    probe = tmp_path / "test_skip_probe.py"
    probe.write_text("import pytest\ndef test_probe():\n    pytest.skip('PG required')\n")
    env = os.environ.copy()
    env.update(MAIL_CORE_REQUIRE_DB="1", MAIL_CORE_DATABASE_URL="unused", TMPDIR=str(tmp_path))
    driver = """
from types import SimpleNamespace
import sys
import pytest
from tests.mail_core.conftest import pytest_runtest_makereport
raise SystemExit(pytest.main([sys.argv[1], '-q'], plugins=[SimpleNamespace(pytest_runtest_makereport=pytest_runtest_makereport)]))
"""
    result = subprocess.run([sys.executable, "-c", driver, str(probe)], cwd=PATH.parents[1],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "database test skipped during required full suite" in result.stdout
    assert "INTERNALERROR" not in result.stdout + result.stderr
