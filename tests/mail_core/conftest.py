"""Shared fixtures / env defaults for mail-core unit tests."""

from __future__ import annotations

import base64
import os
import json
import random
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest
from fastapi.testclient import TestClient

# BlobStore and API lifespan refuse to start without keys — give tests a fixed key.
_TEST_BLOB_KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()
os.environ.setdefault("MAIL_CORE_BLOB_KEY_V1", _TEST_BLOB_KEY)
os.environ.setdefault("MAIL_CORE_BLOB_ACTIVE_VERSION", "1")

# Auth foundation (no insecure production defaults — tests only).
os.environ.setdefault("MAIL_CORE_SECRET_KEY", "test-mail-core-secret-key-not-for-prod")
os.environ.setdefault("MAIL_CORE_LOGIN_PASSWORD", "test-login-password")
os.environ.setdefault("MAIL_CORE_API_KEYS", "test-api-key-for-pytest")

TEST_API_KEY = "test-api-key-for-pytest"

# CI sets MAIL_CORE_REQUIRE_DB=1 so Postgres-backed tests can never silently skip.
if os.environ.get("MAIL_CORE_REQUIRE_DB") == "1" and not os.environ.get("MAIL_CORE_DATABASE_URL"):
    raise pytest.UsageError("MAIL_CORE_REQUIRE_DB=1 but MAIL_CORE_DATABASE_URL is not set")
TEST_LOGIN_PASSWORD = "test-login-password"


def _guard_test_database():
    scripts = str(_SRC.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from test_pg_runtime import SafetyError, guard_database
    try:
        guard_database()
    except SafetyError as exc:
        raise pytest.UsageError(str(exc)) from None
    except Exception as exc:
        raise pytest.UsageError(f"test database verification failed ({type(exc).__name__})") from None


def pytest_configure(config):
    config.addinivalue_line("markers", "db: requires the owned PostgreSQL test runtime")
    if os.environ.get("MAIL_CORE_DATABASE_URL") or os.environ.get("MAIL_CORE_REQUIRE_DB") == "1":
        _guard_test_database()
    elif os.environ.get("KKMAIL_TEST_MODE") != "unit":
        raise pytest.UsageError("select owned DB runtime or explicit quick mode KKMAIL_TEST_MODE=unit")


@pytest.fixture(autouse=True)
def _isolated_backend_runtime(monkeypatch, tmp_path, request):
    from tests.mail_core.runtime_isolation import isolated_runtime
    with isolated_runtime(monkeypatch, tmp_path, request.session):
        yield


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_API_KEY}"}


@pytest.fixture
def api_client(auth_headers):
    """Authenticated TestClient (API key; CSRF skipped for Bearer)."""
    from mail_core.api.app import app

    return TestClient(app, headers=auth_headers)


def pytest_collection_modifyitems(config, items):
    """With MAIL_CORE_REQUIRE_DB=1, any skip caused by a missing DB URL is an error."""
    db_skip_keywords = ("mail_core_database_url", "database required", "pg required", "postgres required")
    for item in items:
        for mark in item.iter_markers("skipif"):
            reason = str(mark.kwargs.get("reason", ""))
            if any(k in reason.lower() for k in db_skip_keywords):
                item.add_marker("db")
                if os.environ.get("MAIL_CORE_REQUIRE_DB") == "1" and mark.args and mark.args[0]:
                    raise pytest.UsageError(f"{item.nodeid} would skip ({reason}) under MAIL_CORE_REQUIRE_DB=1")
    seed = os.environ.get("KKMAIL_TEST_SEED")
    if seed is not None:
        try:
            random.Random(int(seed)).shuffle(items)
        except ValueError:
            raise pytest.UsageError("KKMAIL_TEST_SEED must be an integer") from None


def pytest_sessionfinish(session, exitstatus):
    directory = os.environ.get("KKMAIL_TEST_REPORT_DIR")
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    if not directory or reporter is None:
        return
    target = Path(directory).resolve()
    if not target.is_relative_to(_SRC.parent / ".scratch") or not target.is_dir():
        session.exitstatus = pytest.ExitCode.USAGE_ERROR
        reporter.write_line("test report directory must exist under repository .scratch")
        return
    stats = reporter.stats
    completed = {report.nodeid for category in ("passed", "failed", "error", "skipped")
                 for report in stats.get(category, [])}
    summary = {
        "collected": session.testscollected, "exit_status": int(exitstatus),
        "seed": os.environ.get("KKMAIL_TEST_SEED"),
        "passed": len(stats.get("passed", [])), "failed": len(stats.get("failed", [])),
        "errors": len(stats.get("error", [])),
        "skipped": [{"nodeid": report.nodeid, "reason": str(report.longrepr)} for report in stats.get("skipped", [])],
        "not_executed": [item.nodeid for item in session.items if item.nodeid not in completed],
    }
    (target / "test_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))


def pytest_terminal_summary(terminalreporter):
    seed = os.environ.get("KKMAIL_TEST_SEED")
    if seed is not None:
        terminalreporter.write_line(f"Test order seed={seed}; replay with KKMAIL_TEST_SEED={seed}")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if os.environ.get("MAIL_CORE_REQUIRE_DB") != "1" or not report.skipped:
        return
    reason = str(report.longrepr).lower()
    if any(word in reason for word in ("database", "postgres", "pg required", "mail_core_database_url")):
        report.outcome = "failed"
        report.longrepr = f"{item.nodeid}: database test skipped during required full suite"
