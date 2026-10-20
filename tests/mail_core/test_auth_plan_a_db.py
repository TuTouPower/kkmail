"""Unit tests for Plan A: Login password hash persisted in PostgreSQL."""

from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

import bcrypt

from mail_core.security.auth import (
    AuthConfigError,
    change_login_password,
    get_login_password_hash,
    reset_auth_caches,
    verify_password,
)


def test_auth_plan_a_database_persistence():
    reset_auth_caches()
    stored_cred = {"hash": None}

    class FakeCred:
        def __init__(self, id, hash_val):
            self.id = id
            stored_cred["hash"] = hash_val

        @property
        def login_password_hash(self):
            return stored_cred["hash"]

        @login_password_hash.setter
        def login_password_hash(self, val):
            stored_cred["hash"] = val

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, model, key):
            if stored_cred["hash"]:
                return FakeCred("default", stored_cred["hash"])
            return None

        def add(self, obj):
            stored_cred["hash"] = obj.login_password_hash

        def commit(self):
            pass

    with (
        patch.dict(os.environ, {"MAIL_CORE_DATABASE_URL": "postgresql://test/db", "MAIL_CORE_LOGIN_PASSWORD": "initial_env_password"}),
        patch("mail_core.db.session.get_session_factory", return_value=lambda: FakeSession()),
    ):
        # 1. First boot: DB empty, bootstraps from env
        h1 = get_login_password_hash()
        assert bcrypt.checkpw(b"initial_env_password", h1)
        assert stored_cred["hash"] is not None
        assert bcrypt.checkpw(b"initial_env_password", stored_cred["hash"].encode("utf-8"))
        assert verify_password("initial_env_password")

        # 2. Change password via API
        change_login_password(current="initial_env_password", new="new_changed_password_2026")
        assert verify_password("new_changed_password_2026")
        assert not verify_password("initial_env_password")
        assert bcrypt.checkpw(b"new_changed_password_2026", stored_cred["hash"].encode("utf-8"))

        # 3. Simulate Compose container restart:
        # Memory caches reset, but MAIL_CORE_LOGIN_PASSWORD still has the OLD env password!
        reset_auth_caches()

        # Database is authoritative: must load the new password, NOT the old env password!
        h2 = get_login_password_hash()
        assert bcrypt.checkpw(b"new_changed_password_2026", h2)
        assert verify_password("new_changed_password_2026")
        assert not verify_password("initial_env_password")


def test_change_login_password_fails_closed_on_db_error():
    reset_auth_caches()
    with (
        patch.dict(os.environ, {"MAIL_CORE_DATABASE_URL": "postgresql://test/db", "MAIL_CORE_LOGIN_PASSWORD": "initial_password_1"}),
        patch("mail_core.security.auth._persist_db_password_hash", return_value=False),
    ):
        get_login_password_hash()
        assert verify_password("initial_password_1")

        with pytest.raises(AuthConfigError, match="failed to persist password to database"):
            change_login_password(current="initial_password_1", new="new_password_fails_to_save")

        # Memory cache and verification must remain unchanged
        assert verify_password("initial_password_1")
        assert not verify_password("new_password_fails_to_save")

