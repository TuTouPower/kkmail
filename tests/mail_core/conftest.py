"""Shared fixtures / env defaults for mail-core unit tests."""

from __future__ import annotations

import base64
import os

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
TEST_LOGIN_PASSWORD = "test-login-password"


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_API_KEY}"}


@pytest.fixture
def api_client(auth_headers):
    """Authenticated TestClient (API key; CSRF skipped for Bearer)."""
    from mail_core.api.app import app

    return TestClient(app, headers=auth_headers)
