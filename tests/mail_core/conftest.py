"""Shared fixtures / env defaults for mail-core unit tests."""

from __future__ import annotations

import base64
import os
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


@pytest.fixture(autouse=True)
def _reset_auth_state_for_tests():
    from mail_core.security.auth import reset_auth_caches
    reset_auth_caches()
    if os.environ.get("MAIL_CORE_DATABASE_URL"):
        try:
            from mail_core.db.session import get_session_factory
            from mail_core.mail.storage.models import AuthCredential
            Session = get_session_factory()
            with Session() as session:
                session.query(AuthCredential).delete()
                session.commit()
        except Exception:
            pass
    yield
    reset_auth_caches()
    if os.environ.get("MAIL_CORE_DATABASE_URL"):
        try:
            from mail_core.db.session import get_session_factory
            from mail_core.mail.storage.models import AuthCredential
            Session = get_session_factory()
            with Session() as session:
                session.query(AuthCredential).delete()
                session.commit()
        except Exception:
            pass


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
    if os.environ.get("MAIL_CORE_REQUIRE_DB") != "1":
        return
    db_skip_keywords = ("mail_core_database_url", "database required", "pg required", "postgres required")
    for item in items:
        for mark in item.iter_markers("skipif"):
            reason = str(mark.kwargs.get("reason", ""))
            if any(k in reason.lower() for k in db_skip_keywords) and mark.args and mark.args[0]:
                raise pytest.UsageError(f"{item.nodeid} would skip ({reason}) under MAIL_CORE_REQUIRE_DB=1")
