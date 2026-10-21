"""Unit tests for Plan A: Login password hash persisted in PostgreSQL."""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch

import bcrypt

from mail_core.security.auth import (
    AuthConfigError,
    change_login_password,
    get_login_password_hash,
    invalidate_all_sessions,
    issue_session,
    read_session,
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


def test_session_epoch_persisted_in_database_and_invalidates_across_processes():
    reset_auth_caches()
    stored_cred = {"hash": "dummy_hash", "epoch": 1}

    class FakeCred:
        def __init__(self, id, hash_val, epoch=1):
            self.id = id
            self.login_password_hash = hash_val
            stored_cred["epoch"] = epoch

        @property
        def session_epoch(self):
            return stored_cred["epoch"]

        @session_epoch.setter
        def session_epoch(self, val):
            stored_cred["epoch"] = val

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, model, key):
            return FakeCred("default", stored_cred["hash"], stored_cred["epoch"])

        def add(self, obj):
            stored_cred["epoch"] = obj.session_epoch

        def commit(self):
            pass

    with (
        patch.dict(os.environ, {
            "MAIL_CORE_DATABASE_URL": "postgresql://test/db",
            "MAIL_CORE_SECRET_KEY": "test_secret_key_12345678901234567890",
        }),
        patch("mail_core.db.session.get_session_factory", return_value=lambda: FakeSession()),
    ):
        # 1. Issue session with initial epoch = 1
        cookie_val, csrf = issue_session()
        assert cookie_val is not None
        session_data = read_session(cookie_val)
        assert session_data is not None
        assert session_data["epoch"] == 1
        assert session_data["csrf"] == csrf

        # 2. Invalidate sessions: increment epoch in DB
        invalidate_all_sessions()
        assert stored_cred["epoch"] == 2

        # 3. Old session cookie must be rejected
        assert read_session(cookie_val) is None

        # 4. Issue new session: gets epoch 2
        cookie_val_2, csrf_2 = issue_session()
        session_data_2 = read_session(cookie_val_2)
        assert session_data_2 is not None
        assert session_data_2["epoch"] == 2

        # 5. Simulate another process having stale in-memory epoch = 1,
        # but DB has epoch 2: read_session must check DB and reject cookie with epoch 1
        reset_auth_caches()
        assert read_session(cookie_val) is None
        assert read_session(cookie_val_2) is not None


