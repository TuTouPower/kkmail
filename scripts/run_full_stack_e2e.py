#!/usr/bin/env python3
"""Run Full Stack E2E Tests with Real FastAPI, Worker, Dovecot IMAP & PostgreSQL (t017)."""

from __future__ import annotations

import base64
import contextlib
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if sys.executable != str(ROOT / ".venv/bin/python") and (ROOT / ".venv/bin/python").is_file():
    os.execv(str(ROOT / ".venv/bin/python"), [str(ROOT / ".venv/bin/python"), *sys.argv])

LOG = logging.getLogger("full_stack_e2e")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def load_env_test():
    env_file = ROOT / ".env.test"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip("'\"")
                os.environ.setdefault(k.strip(), v)


def run_cmd(cmd: list[str], **kwargs) -> str:
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT, **kwargs)
    if res.returncode != 0:
        raise RuntimeError(f"Command failed ({res.returncode}): {' '.join(cmd)}\n{res.stderr}")
    return res.stdout.strip()


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_env_test()

    pg_password = os.environ.get("KKMAIL_TEST_PG_PASSWORD")
    if not pg_password:
        LOG.error(
            "KKMAIL_TEST_PG_PASSWORD not provided "
            "(check .env.test on the main branch/worktree; untracked .env.test may be missing in git worktrees / "
            "若在 git worktree 上开发，请到主分支获取未被 git 跟踪的 .env.test)"
        )
        sys.exit(2)

    # 1. Ensure Dovecot IMAP fixture is running
    LOG.info("Checking dedicated test Dovecot IMAP...")
    imap_port = int(os.environ.get("MAIL_CORE_IMAP_PORT", "1143"))
    try:
        with socket.create_connection(("127.0.0.1", imap_port), timeout=1):
            pass
    except OSError:
        LOG.info("Starting Dovecot IMAP via start script...")
        run_cmd([str(ROOT / "scripts/start-mail-core-imap.sh")])

    # 2. Allocate test database
    pg_port = int(os.environ.get("KKMAIL_TEST_PG_PORT", "15433"))
    run_id = uuid.uuid4().hex[:12]
    db_name = f"kkmail_e2e_{run_id}"
    owner_role = f"kkmail_e2e_owner_{run_id}"
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL

    admin_url_obj = URL.create("postgresql+psycopg", username="postgres", password=pg_password, host="127.0.0.1", port=pg_port, database="postgres")
    app_url_obj = URL.create("postgresql+psycopg", username="postgres", password=pg_password, host="127.0.0.1", port=pg_port, database=db_name)
    admin_db_url = admin_url_obj.render_as_string(hide_password=False)
    app_db_url = app_url_obj.render_as_string(hide_password=False)

    engine = create_engine(admin_db_url, isolation_level="AUTOCOMMIT")

    LOG.info("Creating dedicated test database: %s", db_name)
    with engine.connect() as conn:
        conn.execute(text(f'CREATE ROLE "{owner_role}" NOLOGIN'))
        conn.execute(text(f'CREATE DATABASE "{db_name}" OWNER "{owner_role}"'))
        conn.execute(text(f'COMMENT ON DATABASE "{db_name}" IS \'kkmail-e2e-run:{run_id}\''))

    blob_dir = ROOT / ".scratch" / f"e2e_blobs_{run_id}"
    blob_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = ROOT / ".scratch" / "e2e_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = ROOT / ".scratch" / "e2e_artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    app_port = find_free_port()
    secret_key = uuid.uuid4().hex * 2
    blob_key = base64.b64encode(os.urandom(32)).decode()
    e2e_password = "E2E_Test_Pass_123!"

    env = os.environ.copy()
    env.update(
        PYTHONPATH=str(ROOT / "src"),
        MAIL_CORE_DATABASE_URL=app_db_url,
        MAIL_CORE_BLOB_ROOT=str(blob_dir),
        MAIL_CORE_SECRET_KEY=secret_key,
        MAIL_CORE_BLOB_KEY_V1=blob_key,
        MAIL_CORE_BLOB_ACTIVE_VERSION="1",
        MAIL_CORE_LOGIN_PASSWORD=e2e_password,
        KKMAIL_AUTH_PASSWORD=e2e_password,
        MAIL_CORE_ALLOW_PRIVATE_HOSTS="1",
        KKMAIL_FRONTEND_DIST=str(ROOT / "src/frontend/dist"),
        MAIL_CORE_LOG_LEVEL="INFO",
    )

    api_proc = None
    worker_proc = None
    api_log = (logs_dir / f"api_{run_id}.log").open("w", encoding="utf-8")
    worker_log = (logs_dir / f"worker_{run_id}.log").open("w", encoding="utf-8")

    try:
        # 3. Alembic upgrade
        LOG.info("Running database migrations...")
        run_cmd([sys.executable, "-m", "alembic", "-c", "src/mail_core/db/alembic.ini", "upgrade", "head"], env=env)

        # 4. Start API server
        LOG.info("Starting real FastAPI server on port %d...", app_port)
        api_proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "mail_core.api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(app_port),
                "--log-level",
                "info",
            ],
            env=env,
            stdout=api_log,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
        )

        # 5. Start Worker process
        LOG.info("Starting real Worker process...")
        worker_proc = subprocess.Popen(
            [sys.executable, "-m", "mail_core.worker.main"],
            env=env,
            stdout=worker_log,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
        )

        # 6. Wait for healthcheck
        base_url = f"http://127.0.0.1:{app_port}"
        deadline = time.monotonic() + 20
        ready = False
        import urllib.request

        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"{base_url}/health", timeout=1) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.3)

        if not ready:
            raise RuntimeError(f"API server failed to become ready on {base_url}")
        LOG.info("Real FastAPI server ready at %s", base_url)

        # 7. Run Playwright E2E
        LOG.info("Running Playwright Full Stack E2E suite...")
        playwright_cli = ROOT / "src/frontend/node_modules/@playwright/test/cli.js"
        test_env = env.copy()
        test_env.update(
            BASE_URL=base_url,
            E2E_PASSWORD=e2e_password,
            NODE_PATH=str(ROOT / "src/frontend/node_modules"),
        )

        pw_cmd = [
            "node",
            str(playwright_cli),
            "test",
            "tests/e2e/full_stack.spec.ts",
            "-c",
            str(ROOT / "src/frontend/playwright.config.ts"),
        ]
        res = subprocess.run(pw_cmd, cwd=ROOT / "src/frontend", env=test_env)
        if res.returncode != 0:
            LOG.error("Playwright E2E tests failed with code %d", res.returncode)
            sys.exit(res.returncode)
        LOG.info("Playwright Full Stack E2E suite completed successfully.")

    finally:
        # Graceful shutdown
        LOG.info("Tearing down processes and disposable database...")
        for proc, name in [(api_proc, "API"), (worker_proc, "Worker")]:
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

        api_log.close()
        worker_log.close()

        with engine.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
            conn.execute(text(f'DROP ROLE IF EXISTS "{owner_role}"'))
        LOG.info("Cleaned up database %s", db_name)


if __name__ == "__main__":
    main()
