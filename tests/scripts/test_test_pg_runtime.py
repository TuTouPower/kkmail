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


# Non-PG / business-URL strings below are rejection fixtures for guard_database();
# this suite never connects to a SQLite database.
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
    record = {"port": 15433, "database": "kkmail_test_" + "a" * 32, "run_id": "a" * 32}
    monkeypatch.setenv("KKMAIL_TEST_PG_PASSWORD", "pw")
    monkeypatch.setattr(runtime, "ensure_session", lambda: {"session_id": "s"})
    monkeypatch.setattr(runtime, "create_run", lambda: (directory, record))
    monkeypatch.setattr(runtime, "register_run", lambda rid: None)
    monkeypatch.setattr(runtime, "touch_session", lambda: None)
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


def _stub_unit_main(monkeypatch, tmp_path, *, child_code):
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    monkeypatch.setattr(runtime, "RUNS", runs_dir)
    monkeypatch.setattr(runtime, "ROOT", tmp_path)
    captured = {}

    def fake_child(command, env):
        directory = Path(env["KKMAIL_TEST_REPORT_DIR"])
        captured["dir"] = directory
        (directory / "coverage.xml").write_text("<coverage/>")
        (directory / "coverage.json").write_text("{}")
        return child_code

    monkeypatch.setattr(runtime, "child", fake_child)
    monkeypatch.setattr(sys, "argv", ["test_pg_runtime.py", "unit"])
    return runs_dir, captured


def test_unit_mode_removes_run_directory_and_keeps_coverage_summary(monkeypatch, tmp_path):
    runs_dir, captured = _stub_unit_main(monkeypatch, tmp_path, child_code=0)
    assert runtime.main() == 0
    # unit 运行目录不得无限累积；coverage 汇总保留到固定位置
    assert not captured["dir"].exists()
    assert (runs_dir / "unit_coverage.xml").read_text() == "<coverage/>"
    assert (runs_dir / "unit_coverage.json").read_text() == "{}"


def test_unit_mode_removes_run_directory_even_on_failure(monkeypatch, tmp_path):
    runs_dir, captured = _stub_unit_main(monkeypatch, tmp_path, child_code=3)
    assert runtime.main() == 3
    assert not captured["dir"].exists()


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


# --- T083: test service session lifecycle -----------------------------------------

def _isolated_session(monkeypatch, tmp_path, *, state=None):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    monkeypatch.setattr(runtime, "SESSION_DIR", session_dir)
    monkeypatch.setattr(runtime, "SESSION_FILE", session_dir / "session.json")
    monkeypatch.setattr(runtime, "SESSION_LOCK", session_dir / "session.lock")
    monkeypatch.setattr(runtime, "REAPER_LOG", session_dir / "reaper.log")
    monkeypatch.setenv("KKMAIL_TEST_PG_PASSWORD", "pw")
    monkeypatch.setenv("KKMAIL_TEST_SESSION_IDLE_S", "60")
    if state is not None:
        runtime.save_session(state)
    return session_dir


def _state(last_activity, *, reaper_pid=None, runs=None, container_id="cid"):
    from datetime import datetime, timedelta, timezone

    return {
        "session_id": "a" * 32,
        "root": str(runtime.ROOT),
        "container_id": container_id,
        "port": 15433,
        "system_identifier": "sys",
        "created_at": last_activity,
        "last_activity": last_activity,
        "runs": runs or [],
        "reaper_pid": reaper_pid,
    }


def test_reaper_should_close_uses_idle_threshold(monkeypatch, tmp_path):
    _isolated_session(monkeypatch, tmp_path)
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    recent = _state((now - timedelta(seconds=10)).isoformat())
    stale = _state((now - timedelta(seconds=61)).isoformat())
    assert runtime.reaper_should_close(recent, now=now) is False
    assert runtime.reaper_should_close(stale, now=now) is True


def test_session_status_reports_no_session_without_touching_service(monkeypatch, tmp_path):
    _isolated_session(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime, "instance", lambda: pytest.fail("docker invoked"))
    assert runtime.session_status() is None


def test_close_session_without_state_is_noop(monkeypatch, tmp_path):
    _isolated_session(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime, "docker", lambda *a, **k: pytest.fail("docker invoked"))
    assert runtime.close_session("explicit") is False


def test_close_session_cleans_runs_before_removing_containers(monkeypatch, tmp_path):
    events = []
    state = _state("2026-01-01T00:00:00+00:00", runs=["b" * 32])
    _isolated_session(monkeypatch, tmp_path, state=state)
    runs_dir = tmp_path / "runs"
    (runs_dir / ("b" * 32)).mkdir(parents=True)
    monkeypatch.setattr(runtime, "RUNS", runs_dir)
    monkeypatch.setattr(runtime, "session_instance_alive", lambda s: True)
    monkeypatch.setattr(runtime, "load_record", lambda d: {"state": "running", "container_id": "cid"})
    monkeypatch.setattr(runtime, "cleanup", lambda d: events.append("clean"))
    monkeypatch.setattr(runtime, "docker", lambda *a, **k: events.append("down") if "down" in a else "")

    assert runtime.close_session("explicit") is True
    assert events == ["clean", "down"]
    assert not runtime.SESSION_FILE.exists()


def test_ensure_session_reuses_active_session_and_refreshes_activity(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    state = _state(old, reaper_pid=os.getpid())
    _isolated_session(monkeypatch, tmp_path, state=state)
    monkeypatch.setattr(runtime, "session_instance_alive", lambda s: True)
    monkeypatch.setattr(runtime, "start", lambda: pytest.fail("service restarted"))
    monkeypatch.setattr(runtime, "spawn_reaper", lambda s: None)

    result = runtime.ensure_session()
    assert result["last_activity"] != old
    assert runtime.load_session()["last_activity"] == result["last_activity"]


def test_ensure_session_rebuilds_after_stale_state(monkeypatch, tmp_path):
    state = _state("2026-01-01T00:00:00+00:00", runs=["b" * 32])
    _isolated_session(monkeypatch, tmp_path, state=state)
    events = []
    monkeypatch.setattr(runtime, "session_instance_alive", lambda s: False)
    monkeypatch.setattr(runtime, "_clean_registered_runs", lambda s: events.append("clean"))
    monkeypatch.setattr(runtime, "docker", lambda *a, **k: events.append("down"))
    monkeypatch.setattr(runtime, "start", lambda: events.append("up"))
    monkeypatch.setattr(runtime, "instance", lambda: ("newcid", 15433))
    monkeypatch.setattr(runtime, "engine", lambda u: _Conn())
    monkeypatch.setattr(runtime, "spawn_reaper", lambda s: None)

    result = runtime.ensure_session()
    assert events == ["clean", "down", "up"]
    assert result["container_id"] == "newcid"
    assert result["runs"] == []
    assert not runtime.load_session()["last_activity"].startswith("2026-01-01")


class _Conn:
    def connect(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def scalar(self, statement):
        return "sys"


def test_run_registers_and_touches_session(monkeypatch, tmp_path):
    directory = tmp_path / "run"
    record = {"port": 15433, "database": "kkmail_test_" + "a" * 32, "run_id": "a" * 32}
    ensured = []
    monkeypatch.setattr(runtime, "ensure_session", lambda: ensured.append(1) or {"session_id": "s"})
    monkeypatch.setattr(runtime, "create_run", lambda: (directory, record))
    registrations = []
    touches = []
    monkeypatch.setattr(runtime, "register_run", lambda rid: registrations.append(rid))
    monkeypatch.setattr(runtime, "touch_session", lambda: touches.append(1))
    monkeypatch.setattr(runtime, "guard_database", lambda: None)
    monkeypatch.setenv("KKMAIL_TEST_PG_PASSWORD", "pw")

    def fake_child(command, env):
        return 0

    monkeypatch.setattr(runtime, "child", fake_child)
    monkeypatch.setattr(runtime, "cleanup", lambda d: None)

    assert runtime.run([]) == 0
    assert ensured == [1]
    assert registrations == ["a" * 32]
    assert touches == [1]


def test_reaper_keeps_session_while_a_test_run_is_active(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone

    _isolated_session(monkeypatch, tmp_path)
    monkeypatch.setenv("KKMAIL_TEST_SESSION_MAX_RUN_S", "120")
    now = datetime.now(timezone.utc)
    state = _state((now - timedelta(seconds=120)).isoformat(), runs=["a" * 32])
    state["active_runs"] = {"a" * 32: {"started_at": (now - timedelta(seconds=10)).isoformat(), "pid": os.getpid()}}
    assert runtime.reaper_should_close(state, now=now) is False
    state["active_runs"] = {"a" * 32: {"started_at": (now - timedelta(seconds=121)).isoformat(), "pid": os.getpid()}}
    assert runtime.reaper_should_close(state, now=now) is True


def test_explicit_close_refuses_while_a_run_is_active(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    state = _state(now.isoformat())
    state["active_runs"] = {"a" * 32: {"started_at": now.isoformat(), "pid": os.getpid()}}
    _isolated_session(monkeypatch, tmp_path, state=state)
    monkeypatch.setattr(runtime, "docker", lambda *a, **k: pytest.fail("docker invoked"))
    with pytest.raises(runtime.SafetyError, match="active test runs"):
        runtime.close_session("explicit")


def test_spawn_reaper_preserves_concurrent_registry_updates(monkeypatch, tmp_path):
    from types import SimpleNamespace

    state = _state("2026-01-01T00:00:00+00:00")
    _isolated_session(monkeypatch, tmp_path, state=state)
    concurrent = dict(state, runs=["b" * 32])
    runtime.save_session(concurrent)  # a run registered while reaper was starting
    monkeypatch.setattr(runtime, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=4242))

    runtime.spawn_reaper(state)

    current = runtime.load_session()
    assert current["runs"] == ["b" * 32]
    assert current["reaper_pid"] == 4242


def test_reaper_loop_retries_after_a_failed_cycle(monkeypatch, tmp_path):
    state = _state("2026-01-01T00:00:00+00:00", reaper_pid=os.getpid())
    _isolated_session(monkeypatch, tmp_path, state=state)
    monkeypatch.setattr(runtime.time, "sleep", lambda seconds: None)
    loads = {"n": 0}

    def fake_load():
        loads["n"] += 1
        return state if loads["n"] <= 2 else None

    monkeypatch.setattr(runtime, "load_session", fake_load)
    closes = []

    def fake_close(reason, *, only_if_idle=False):
        closes.append(reason)
        if len(closes) == 1:
            raise RuntimeError("transient docker failure")
        raise SystemExit

    monkeypatch.setattr(runtime, "close_session", fake_close)
    with pytest.raises(SystemExit):
        runtime.reaper_loop()
    assert len(closes) == 2


def test_ensure_session_respawns_dead_reaper_without_reentrant_lock(monkeypatch, tmp_path):
    import contextlib
    from types import SimpleNamespace

    state = _state("2026-01-01T00:00:00+00:00", reaper_pid=4242)
    _isolated_session(monkeypatch, tmp_path, state=state)
    monkeypatch.setattr(runtime, "session_instance_alive", lambda s: True)
    monkeypatch.setattr(runtime, "_pid_alive", lambda pid: False)
    monkeypatch.setattr(runtime.subprocess, "Popen", lambda *a, **k: SimpleNamespace(pid=5252))

    held = {"value": False}

    @contextlib.contextmanager
    def detecting_lock():
        assert not held["value"], "session_lock reentered"
        held["value"] = True
        try:
            yield
        finally:
            held["value"] = False

    monkeypatch.setattr(runtime, "session_lock", detecting_lock)
    result = runtime.ensure_session()
    assert result["reaper_pid"] is None  # stale pid cleared before respawn
    assert runtime.load_session()["reaper_pid"] == 5252


def test_dead_pid_does_not_block_idle_reclaim(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone

    _isolated_session(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime, "_pid_alive", lambda pid: False)
    now = datetime.now(timezone.utc)
    state = _state((now - timedelta(seconds=120)).isoformat())
    state["active_runs"] = {"a" * 32: {"started_at": now.isoformat(), "pid": 999999}}
    assert runtime.reaper_should_close(state, now=now) is True
