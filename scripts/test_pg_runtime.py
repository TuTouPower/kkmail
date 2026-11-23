"""Owned PostgreSQL test runs; no application database or secret is reused."""

from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / ".scratch" / "test_runs"
SESSION_DIR = ROOT / ".scratch" / "test_session"
SESSION_FILE = SESSION_DIR / "session.json"
SESSION_LOCK = SESSION_DIR / "session.lock"
REAPER_LOG = SESSION_DIR / "reaper.log"
COMPOSE = ["compose", "-p", "kkmail_test", "-f", str(ROOT / "config/test_pg_compose.yaml")]
LOG = logging.getLogger("test_pg_runtime")
DEFAULT_SESSION_IDLE_S = 900
DEFAULT_MAX_RUN_S = 7200
REAPER_POLL_S = 15


class SafetyError(RuntimeError):
    """A test target could not be proven safe; no destructive fallback."""


_CREDENTIAL_ASSIGNMENT_RE = re.compile(
    r"(?i)([a-z0-9_]*(?:password|passwd|pwd|token|secret|api[_-]?key)[a-z0-9_]*)(\s*[:=]\s*)\S+"
)
_URL_PASSWORD_RE = re.compile(r"(://[^\s:/@]+:)[^\s@]+(@)")


def _redacted_diagnostic(stderr, *, limit: int = 500) -> str:
    """回显 stderr 诊断尾段，但先脱敏凭据赋值与 URL 密码（A307）。

    旧实现整段丢弃 stderr，docker 故障（守护进程/端口/配置）不可诊断；
    直接回显又可能带出展开的环境变量值，故只对凭据模式做替换后回显尾段。
    """
    text = (stderr or "").strip()
    if not text:
        return ""
    text = _CREDENTIAL_ASSIGNMENT_RE.sub(r"\1\2***", text)
    text = _URL_PASSWORD_RE.sub(r"\1***\2", text)
    return text[-limit:]


def docker(*args):
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True)
    except FileNotFoundError:
        # Gate policy (T5): the default gate requires the dedicated test
        # PostgreSQL service. Fail explicitly with the way out instead of
        # an obscure FileNotFoundError deep in the run.
        raise SafetyError(
            "docker executable not found: the default test gate requires the dedicated "
            "PostgreSQL test service. Install/start Docker and re-run, or use the explicit "
            "quick mode 'scripts/run-mail-core-tests.sh unit' (unit does NOT execute the "
            "PostgreSQL suite and is not a full pass)"
        ) from None
    if result.returncode:
        detail = _redacted_diagnostic(result.stderr)
        message = "Docker command failed; check daemon, port and test-only configuration"
        if detail:
            message += f": {detail}"
        raise SafetyError(message)
    return result.stdout.strip()


def password():
    value = os.environ.get("KKMAIL_TEST_PG_PASSWORD", "")
    if not value:
        raise SafetyError(
            "provide operator-supplied KKMAIL_TEST_PG_PASSWORD "
            "(check .env.test on the main branch/worktree; untracked .env.test may be missing in git worktrees / "
            "若在 git worktree 上开发，请到主分支获取未被 git 跟踪的 .env.test)"
        )
    return value


def instance():
    cid = docker(*COMPOSE, "ps", "-q", "postgres")
    if not cid or "\n" in cid:
        raise SafetyError("dedicated test container is not running")
    info = json.loads(docker("inspect", cid))[0]
    if info["Config"]["Labels"].get("io.kkmail.test_pg") != "v1":
        raise SafetyError("unregistered test instance")
    bindings = info["NetworkSettings"]["Ports"].get("5432/tcp") or []
    if len(bindings) != 1 or bindings[0]["HostIp"] != "127.0.0.1":
        raise SafetyError("test PostgreSQL must bind only to loopback")
    return info["Id"], int(bindings[0]["HostPort"])


def admin_url(port):
    return URL.create("postgresql+psycopg", username="postgres", password=password(),
                      host="127.0.0.1", port=port, database="postgres")


def engine(url):
    return create_engine(url, poolclass=NullPool, connect_args={"connect_timeout": 5},
                         hide_parameters=True)


def checked_url(raw):
    try:
        url = make_url(raw)
        valid = (url.drivername in ("postgresql", "postgresql+psycopg")
                 and url.host == "127.0.0.1" and not url.query
                 and re.fullmatch(r"kkmail_test_[0-9a-f]{32}", url.database or ""))
    except Exception:
        valid = False
    if not valid:
        raise SafetyError("refusing non-owned test database URL (query overrides are forbidden)")
    return url.set(drivername="postgresql+psycopg")


def write_record(directory, record):
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / "ownership.tmp"
    with temporary.open("w") as handle:
        os.chmod(temporary, 0o600)
        json.dump(record, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(directory / "ownership.json")


def load_record(directory):
    directory = Path(directory).resolve()
    if directory.parent != RUNS.resolve() or not re.fullmatch(r"[0-9a-f]{32}", directory.name):
        raise SafetyError("ownership record must belong to this repository test run")
    try:
        record = json.loads((directory / "ownership.json").read_text())
    except (OSError, ValueError):
        raise SafetyError("missing or invalid test run ownership record") from None
    if (record.get("run_id") != directory.name
            or record.get("database") != "kkmail_test_" + directory.name
            or record.get("owner_role") != "kkmail_test_owner_" + directory.name
            or record.get("root") != str(ROOT)):
        raise SafetyError("ownership record identity mismatch")
    return record


def verify_instance(record):
    cid, port = instance()
    if record["container_id"] != cid or record["port"] != port:
        raise SafetyError("test instance ownership mismatch")
    with engine(admin_url(port)).connect() as connection:
        actual = str(connection.scalar(text("SELECT system_identifier FROM pg_control_system()")))
    if actual != record["system_identifier"]:
        raise SafetyError("PostgreSQL cluster identity mismatch")


def guard_database():
    """Called by direct pytest before collection and before every fixture mutation."""
    url = checked_url(os.environ.get("MAIL_CORE_DATABASE_URL", ""))
    directory = os.environ.get("KKMAIL_TEST_RUN_DIR")
    if not directory:
        raise SafetyError("missing test run ownership directory")
    record = load_record(directory)
    if (url.database != record["database"] or url.port != record["port"]
            or url.username != "postgres" or url.password != password()
            or record["state"] != "running"):
        raise SafetyError("database URL does not match active run ownership")
    verify_instance(record)
    with engine(url).connect() as connection:
        marker, owner = connection.execute(text("SELECT shobj_description(oid, 'pg_database'), pg_get_userbyid(datdba) "
                                                "FROM pg_database WHERE datname = current_database()")).one()
    if marker != record["marker"] or owner != record["owner_role"]:
        raise SafetyError("database ownership marker mismatch")
    return record



def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def session_idle_seconds() -> int:
    raw = os.environ.get("KKMAIL_TEST_SESSION_IDLE_S", "")
    try:
        value = int(raw) if raw else DEFAULT_SESSION_IDLE_S
    except ValueError:
        value = DEFAULT_SESSION_IDLE_S
    return max(1, value)


@contextlib.contextmanager
def session_lock():
    """Serialize all session state transitions with an advisory file lock."""
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    with SESSION_LOCK.open("a+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load_session():
    try:
        state = json.loads(SESSION_FILE.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get("root") != str(ROOT):
        return None
    if not state.get("session_id") or not state.get("container_id"):
        return None
    return state


def save_session(state):
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    temporary = SESSION_DIR / "session.tmp"
    with temporary.open("w") as handle:
        os.chmod(temporary, 0o600)
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(SESSION_FILE)


def _pid_alive(pid):
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def max_run_seconds() -> int:
    raw = os.environ.get("KKMAIL_TEST_SESSION_MAX_RUN_S", "")
    try:
        value = int(raw) if raw else DEFAULT_MAX_RUN_S
    except ValueError:
        value = DEFAULT_MAX_RUN_S
    return max(60, value)


def fresh_active_runs(state, *, now=None):
    """Active runs still younger than the hard run ceiling own the session."""
    now = now or _utc_now()
    active = state.get("active_runs") or {}
    fresh = []
    for run_id, info in active.items():
        if not isinstance(info, dict) or not info.get("started_at"):
            continue
        started = datetime.fromisoformat(info["started_at"])
        if ((now - started).total_seconds() < max_run_seconds()
                and _pid_alive(info.get("pid"))):
            fresh.append(run_id)
    return fresh


def reaper_should_close(state, *, now=None):
    """Idle decision: a live test run always keeps its session alive."""
    now = now or _utc_now()
    if fresh_active_runs(state, now=now):
        return False
    last = datetime.fromisoformat(state["last_activity"])
    return (now - last).total_seconds() >= session_idle_seconds()


def session_instance_alive(state):
    try:
        cid, port = instance()
    except SafetyError:
        return False
    return cid == state["container_id"] and port == state["port"]


def session_status():
    state = load_session()
    if state is None:
        return None
    alive = session_instance_alive(state)
    idle = (_utc_now() - datetime.fromisoformat(state["last_activity"])).total_seconds()
    return {
        "session_id": state["session_id"],
        "container_id": state["container_id"],
        "port": state["port"],
        "alive": alive,
        "idle_seconds": max(0, int(idle)),
        "idle_timeout_seconds": session_idle_seconds(),
        "runs": len(state.get("runs", [])),
        "reaper_pid": state.get("reaper_pid"),
    }


def _clean_registered_runs(state):
    """Best-effort cleanup of every run owned by a session, registry first."""
    run_ids = set(state.get("runs", []))
    if session_instance_alive(state) and RUNS.exists():
        # Also adopt interrupted runs whose ids never reached the registry.
        for directory in RUNS.iterdir():
            if not directory.is_dir():
                continue
            try:
                record = load_record(directory)
            except SafetyError:
                continue
            if record.get("container_id") == state["container_id"] and record.get("state") != "cleaned":
                run_ids.add(directory.name)
    for run_id in sorted(run_ids):
        directory = RUNS / run_id
        if not directory.exists():
            continue
        try:
            record = load_record(directory)
            if record.get("state") != "cleaned":
                cleanup(directory)
        except SafetyError:
            LOG.warning("session close skipped unsafe run cleanup run=%s", run_id)


def close_session(reason, *, only_if_idle=False):
    """Tear a session down: clean its databases first, then remove containers."""
    with session_lock():
        state = load_session()
        if state is None:
            return False
        if only_if_idle and not reaper_should_close(state):
            return False
        if fresh_active_runs(state):
            raise SafetyError("refusing session close: active test runs remain")
        _clean_registered_runs(state)
        docker(*COMPOSE, "down", "--remove-orphans")
        SESSION_FILE.unlink(missing_ok=True)
        LOG.info("test session closed reason=%s session=%s", reason, state["session_id"][:12])
    reaper_pid = state.get("reaper_pid")
    if reaper_pid and reaper_pid != os.getpid() and _pid_alive(reaper_pid):
        try:
            os.kill(reaper_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    return True


def spawn_reaper(state):
    if _pid_alive(state.get("reaper_pid")):
        return
    REAPER_LOG.parent.mkdir(parents=True, exist_ok=True)
    with REAPER_LOG.open("ab") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "reaper"],
            cwd=ROOT, env=os.environ.copy(), stdin=subprocess.DEVNULL,
            stdout=log, stderr=log, start_new_session=True,
        )
    with session_lock():
        current = load_session()
        if current is None or current.get("session_id") != state["session_id"]:
            # Session changed while the watchdog started; never adopt it.
            try:
                os.kill(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            return
        current["reaper_pid"] = process.pid
        save_session(current)


def reaper_loop():
    """Idle watchdog; survives transient failures, exits on session change."""
    LOG.info("test session reaper started pid=%s", os.getpid())
    while True:
        time.sleep(REAPER_POLL_S)
        try:
            with session_lock():
                state = load_session()
                if state is None or state.get("reaper_pid") != os.getpid():
                    return
            close_session("idle", only_if_idle=True)
        except Exception:
            # A failed cleanup must not permanently strand a live session.
            LOG.exception("reaper cycle failed; retrying")


def ensure_session():
    """Return the active session, creating one lazily when none exists."""
    password()
    with session_lock():
        state = load_session()
        if state is not None and session_instance_alive(state):
            state["last_activity"] = _utc_now().isoformat()
            reaper_alive = _pid_alive(state.get("reaper_pid"))
            if not reaper_alive:
                state["reaper_pid"] = None
            save_session(state)
        else:
            state = None
    if state is not None:
        # spawn_reaper takes session_lock itself; never call it inside the lock.
        if not reaper_alive:
            spawn_reaper(state)
        return state
    with session_lock():
        stale = load_session()
        if stale is not None:
            # Stale registry: clean what is still reachable, then discard it.
            _clean_registered_runs(stale)
            docker(*COMPOSE, "down", "--remove-orphans")
            SESSION_FILE.unlink(missing_ok=True)
        start()
        cid, port = instance()
        with engine(admin_url(port)).connect() as connection:
            system_id = str(connection.scalar(text("SELECT system_identifier FROM pg_control_system()")))
        state = {
            "session_id": uuid.uuid4().hex,
            "root": str(ROOT),
            "container_id": cid,
            "port": port,
            "system_identifier": system_id,
            "created_at": _utc_now().isoformat(),
            "last_activity": _utc_now().isoformat(),
            "runs": [],
            "reaper_pid": None,
        }
        save_session(state)
    spawn_reaper(state)
    return state


def touch_session():
    with session_lock():
        state = load_session()
        if state is None:
            return
        state["last_activity"] = _utc_now().isoformat()
        save_session(state)


def register_run(run_id):
    with session_lock():
        state = load_session()
        if state is None:
            return
        if run_id not in state["runs"]:
            state["runs"].append(run_id)
        state.setdefault("active_runs", {})[run_id] = {
            "started_at": _utc_now().isoformat(),
            "pid": os.getpid(),
        }
        save_session(state)


def unregister_run(run_id):
    with session_lock():
        state = load_session()
        if state is None:
            return
        if state.setdefault("active_runs", {}).pop(run_id, None) is not None:
            save_session(state)


def start():
    password()
    existing = docker(*COMPOSE, "ps", "-a", "-q", "postgres")
    if existing:
        info = json.loads(docker("inspect", existing))[0]
        if info["Config"]["Labels"].get("io.kkmail.test_pg") != "v1":
            raise SafetyError("refusing to start an unregistered test instance")
        if not info["State"]["Running"]:
            docker("start", existing)
        # Never recreate a running shared instance when a second repository starts.
    else:
        docker(*COMPOSE, "up", "-d", "--wait", "--wait-timeout", "90")
    cid, port = instance()
    # Readiness includes password authentication, not just pg_isready.
    deadline = time.monotonic() + 30
    while True:
        try:
            with engine(admin_url(port)).connect() as connection:
                connection.execute(text("SELECT 1"))
            break
        except OperationalError:
            if time.monotonic() >= deadline:
                raise SafetyError("dedicated test PostgreSQL authentication/readiness timed out") from None
            time.sleep(0.25)
    LOG.info("dedicated test PostgreSQL ready container=%s port=%s", cid[:12], port)


def create_run():
    cid, port = instance()
    run_id = uuid.uuid4().hex
    directory = RUNS / run_id
    with engine(admin_url(port)).connect() as connection:
        system_id = str(connection.scalar(text("SELECT system_identifier FROM pg_control_system()")))
    record = dict(run_id=run_id, root=str(ROOT), database="kkmail_test_" + run_id,
                  owner_role="kkmail_test_owner_" + run_id,
                  container_id=cid, port=port, system_identifier=system_id,
                  marker="kkmail-test-run:" + run_id, state="creating",
                  created_at=datetime.now().astimezone().isoformat())
    write_record(directory, record)
    try:
        # CREATE DATABASE assigns ownership atomically, including interruption
        # between creation and COMMENT. The per-run role cannot log in.
        with engine(admin_url(port)).connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(text(f'CREATE ROLE "{record["owner_role"]}" NOLOGIN'))
            connection.execute(text(f'CREATE DATABASE "{record["database"]}" OWNER "{record["owner_role"]}"'))
            connection.execute(text(f'COMMENT ON DATABASE "{record["database"]}" IS \'{record["marker"]}\''))
        record["state"] = "running"
        write_record(directory, record)
    except BaseException:
        cleanup(directory)
        raise
    return directory, record


def cleanup(directory):
    record = load_record(directory)
    verify_instance(record)
    with engine(admin_url(record["port"])).connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        database = connection.execute(text("SELECT shobj_description(oid, 'pg_database'), pg_get_userbyid(datdba) "
                                           "FROM pg_database WHERE datname=:db"), {"db": record["database"]}).first()
        if database:
            marker, owner = database
            if (owner != record["owner_role"] or
                    (marker != record["marker"] and not (record["state"] == "creating" and marker is None))):
                raise SafetyError("refusing cleanup: database ownership marker mismatch")
            connection.execute(text(f'DROP DATABASE "{record["database"]}" WITH (FORCE)'))
        role = connection.execute(text("SELECT rolcanlogin FROM pg_roles WHERE rolname=:role"),
                                  {"role": record["owner_role"]}).first()
        if role:
            if role[0]:
                raise SafetyError("refusing cleanup: test owner role can log in")
            connection.execute(text(f'DROP ROLE "{record["owner_role"]}"'))
    record["state"] = "cleaned"
    write_record(Path(directory), record)
    LOG.info("cleaned run=%s", record["run_id"])


@contextlib.contextmanager
def stage(name):
    begun = time.monotonic()
    status = "failed"
    try:
        yield
        status = "passed"
    finally:
        LOG.info("stage=%s status=%s seconds=%.3f", name, status, time.monotonic() - begun)


def child(command, env):
    process = subprocess.Popen(command, cwd=ROOT, env=env, start_new_session=True)
    try:
        return process.wait()
    finally:
        # Also stop descendants spawned by tests before dropping their database.
        # 仅当子进程本体仍在运行时才向其进程组发信号：wait 已返回退出后
        # pgid 可能被系统回收给无关进程组，无条件 killpg 有误伤时序窗（A363）。
        # 子进程仍在运行则其 pgid 仍归它所有（组长未退出，pgid 不会被回收）。
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            deadline = time.monotonic() + 10
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def run_environment(directory):
    env = {key: value for key, value in os.environ.items() if not key.startswith("MAIL_CORE_")}
    pg_client_dir = str(ROOT / "scripts" / "test_pg_client")
    path = os.environ.get("PATH", "")
    env.update(PYTHONPATH=str(ROOT / "src"),
               PATH=f"{pg_client_dir}:{path}",
               KKMAIL_TEST_REPORT_DIR=str(directory),
               COVERAGE_FILE=str(directory / ".coverage"),
               MAIL_CORE_BLOB_ROOT=str(directory / "blobs"), MAIL_CORE_BACKUP_DIR=str(directory / "backups"),
               MAIL_CORE_DATA_DIR=str(directory / "data"), TMPDIR=str(directory / "tmp"))
    for subdir in ("blobs", "backups", "data", "tmp"):
        (directory / subdir).mkdir(parents=True)
    for key in ("MAIL_CORE_BLOB_KEY_V1", "MAIL_CORE_BACKUP_KEY"):
        env[key] = base64.b64encode(os.urandom(32)).decode()
    env.update(MAIL_CORE_BLOB_ACTIVE_VERSION="1", MAIL_CORE_SECRET_KEY=os.urandom(32).hex())
    return env


def run(args):
    directory = None
    record = None
    outcome_error = None
    try:
        with stage("allocate"):
            # Gate policy (T5): a default run must have the test PostgreSQL
            # service. ensure_session creates a session on demand and reuses a
            # live one; failure is explicit, never a silent unit-mode downgrade.
            ensure_session()
            directory, record = create_run()
            register_run(record["run_id"])
            env = run_environment(directory)
            env.update(MAIL_CORE_DATABASE_URL=admin_url(record["port"]).set(database=record["database"]).render_as_string(hide_password=False),
                       KKMAIL_TEST_RUN_DIR=str(directory), MAIL_CORE_REQUIRE_DB="1", KKMAIL_TEST_MODE="full")
            # Guard before Alembic, as well as in direct pytest.
            old_env = os.environ.copy()
            try:
                os.environ.update(env)
                guard_database()
            finally:
                os.environ.clear()
                os.environ.update(old_env)
        with stage("migrate"):
            code = child([sys.executable, "-m", "alembic", "-c", "src/mail_core/db/alembic.ini", "upgrade", "head"], env)
            if code:
                raise TestFailure(code)
        with stage("tests"):
            code = child([sys.executable, "-m", "pytest", "tests", "-q", "--tb=short",
                          "-ra", "--cov=mail_core", "--cov-branch", "--cov-report=term:skip-covered",
                          "--cov-report=xml:" + str(directory / "coverage.xml"),
                          "--cov-report=json:" + str(directory / "coverage.json"),
                          "--basetemp", str(directory / "tmp" / "pytest"),
                          "--junitxml", str(directory / "junit.xml"), *args], env)
            if code:
                raise TestFailure(code)
        return 0
    except BaseException as exc:
        # 先记下在途结果，finally 的 cleanup 失败不得将其掩盖（A134）
        outcome_error = exc
        raise
    finally:
        if directory:
            with stage("cleanup"):
                try:
                    cleanup(directory)
                except Exception:
                    if outcome_error is not None:
                        LOG.exception("cleanup failed; preserving the original run outcome")
                    else:
                        raise
        if record is not None:
            unregister_run(record["run_id"])
        # Any invocation counts as test activity, including a failed run.
        touch_session()


class TestFailure(Exception):
    def __init__(self, code):
        self.code = code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "cleanup", "unit", "session-status", "session-end", "reaper"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        if args.action == "session-status":
            status = session_status()
            if status is None:
                print("no active test session")
            else:
                print(json.dumps(status, indent=2, sort_keys=True))
        elif args.action == "session-end":
            if not close_session("explicit"):
                LOG.info("no active test session")
        elif args.action == "reaper":
            reaper_loop()
        elif args.action == "cleanup":
            if len(args.arguments) != 1:
                raise SafetyError("cleanup requires one exact run UUID")
            cleanup(RUNS / args.arguments[0])
        elif args.action == "unit":
            directory = RUNS / ("unit_" + uuid.uuid4().hex)
            env = run_environment(directory)
            env["KKMAIL_TEST_MODE"] = "unit"
            env.pop("KKMAIL_TEST_PG_PASSWORD", None)
            env.pop("KKMAIL_TEST_RUN_DIR", None)
            LOG.warning("quick mode: PostgreSQL suite NOT executed")
            try:
                return child([sys.executable, "-m", "pytest", "tests", "-q", "-ra",
                              "--cov=mail_core", "--cov-branch", "--cov-report=term:skip-covered",
                              "--cov-report=xml:" + str(directory / "coverage.xml"),
                              "--cov-report=json:" + str(directory / "coverage.json"), "--basetemp",
                              str(directory / "tmp" / "pytest"), *args.arguments], env)
            finally:
                # unit 运行目录不累积（A265）：coverage 汇总先抢救到固定位置
                # （每次覆盖，只留最近一次），其余产物随目录一并删除。
                for name, fixed in (("coverage.xml", "unit_coverage.xml"),
                                    ("coverage.json", "unit_coverage.json")):
                    try:
                        shutil.copyfile(directory / name, RUNS / fixed)
                    except OSError:
                        pass
                shutil.rmtree(directory, ignore_errors=True)
        else:
            return run(args.arguments)
        return 0
    except TestFailure as exc:
        return exc.code
    except KeyboardInterrupt:
        LOG.error("test run interrupted")
        return 130
    except SafetyError as exc:
        LOG.error("%s", exc)
        return 2
    except Exception as exc:
        # Connection and SQL exceptions may contain credentials: report type only.
        LOG.error("test runtime failed (%s); inspect dedicated test service", type(exc).__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
