"""Owned PostgreSQL test runs; no application database or secret is reused."""

from __future__ import annotations

import argparse
import base64
import contextlib
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import re
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
COMPOSE = ["compose", "-p", "kkmail_test_pg", "-f", str(ROOT / "config/test_pg_compose.yaml")]
LOG = logging.getLogger("test_pg_runtime")


class SafetyError(RuntimeError):
    """A test target could not be proven safe; no destructive fallback."""


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode:
        # Docker may include expanded environment values in diagnostics.
        raise SafetyError("Docker command failed; check daemon, port and test-only configuration")
    return result.stdout.strip()


def password():
    value = os.environ.get("KKMAIL_TEST_PG_PASSWORD", "")
    if not value:
        raise SafetyError("provide operator-supplied KKMAIL_TEST_PG_PASSWORD")
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
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def run_environment(directory):
    env = {key: value for key, value in os.environ.items() if not key.startswith("MAIL_CORE_")}
    env.update(PYTHONPATH=str(ROOT / "src"),
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
    try:
        with stage("allocate"):
            directory, record = create_run()
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
                          "--basetemp", str(directory / "tmp" / "pytest"),
                          "--junitxml", str(directory / "junit.xml"), *args], env)
            if code:
                raise TestFailure(code)
        return 0
    finally:
        if directory:
            with stage("cleanup"):
                cleanup(directory)


class TestFailure(Exception):
    def __init__(self, code):
        self.code = code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "stop", "run", "cleanup", "unit"))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    def interrupted(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        if args.action == "start":
            with stage("start"):
                start()
        elif args.action == "stop":
            _, port = instance()
            with engine(admin_url(port)).connect() as connection:
                active = connection.scalar(text("SELECT count(*) FROM pg_database WHERE "
                                                "shobj_description(oid, 'pg_database') LIKE 'kkmail-test-run:%'"))
            if active:
                raise SafetyError("refusing stop: owned test databases remain")
            docker(*COMPOSE, "stop", "postgres")
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
            return child([sys.executable, "-m", "pytest", "tests", "-q", "--basetemp",
                          str(directory / "tmp" / "pytest"), *args.arguments], env)
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
