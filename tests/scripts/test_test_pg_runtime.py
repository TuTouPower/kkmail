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


def test_child_does_not_signal_group_after_process_already_exited(monkeypatch):
    killed = []

    class FakeProcess:
        pid = 424242

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **k: FakeProcess())
    monkeypatch.setattr(runtime.os, "killpg", lambda pgid, sig: killed.append((pgid, sig)))
    assert runtime.child(["true"], {}) == 0
    # wait 已确认子进程退出后不得再 killpg：pgid 可能已被系统回收给无关进程组
    assert killed == []


def _stub_run_pipeline(monkeypatch, tmp_path, *, test_code, cleanup_side_effect=None):
    """把 run() 的外部依赖全部替身化，只保留 allocate/migrate/tests/cleanup 编排。"""
    directory = tmp_path / "run"
    record = {"port": 15433, "database": "kkmail_test_" + "a" * 32}
    monkeypatch.setenv("KKMAIL_TEST_PG_PASSWORD", "pw")
    monkeypatch.setattr(runtime, "instance", lambda: ("cid", 15433))
    monkeypatch.setattr(runtime, "create_run", lambda: (directory, record))
    monkeypatch.setattr(runtime, "guard_database", lambda: None)
    calls = {"n": 0}

    def fake_child(command, env):
        calls["n"] += 1
        return 0 if calls["n"] == 1 else test_code  # migrate 成功，tests 返回 test_code

    monkeypatch.setattr(runtime, "child", fake_child)
    if cleanup_side_effect is not None:
        monkeypatch.setattr(runtime, "cleanup", cleanup_side_effect)
    else:
        monkeypatch.setattr(runtime, "cleanup", lambda d: None)
    return directory


def test_run_preserves_test_failure_code_when_cleanup_raises(monkeypatch, tmp_path):
    def bad_cleanup(directory):
        raise RuntimeError("cleanup boom")

    _stub_run_pipeline(monkeypatch, tmp_path, test_code=7, cleanup_side_effect=bad_cleanup)
    with pytest.raises(runtime.TestFailure) as excinfo:
        runtime.run([])
    # finally 中 cleanup 抛错不得掩盖测试失败退出码
    assert excinfo.value.code == 7


def test_run_surfaces_cleanup_error_when_tests_passed(monkeypatch, tmp_path):
    def bad_cleanup(directory):
        raise RuntimeError("cleanup boom")

    _stub_run_pipeline(monkeypatch, tmp_path, test_code=0, cleanup_side_effect=bad_cleanup)
    with pytest.raises(RuntimeError, match="cleanup boom"):
        runtime.run([])


def test_run_returns_zero_when_all_stages_pass(monkeypatch, tmp_path):
    _stub_run_pipeline(monkeypatch, tmp_path, test_code=0)
    assert runtime.run([]) == 0


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
