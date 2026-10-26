"""Unit tests for Plan A: Login password hash persisted in PostgreSQL."""

from __future__ import annotations

import os
import pytest
from unittest.mock import patch

import bcrypt

from mail_core.security.auth import (
    _SESSION_EPOCH_CACHE_TTL_SECONDS,
    AuthConfigError,
    change_login_password,
    get_login_password_hash,
    get_session_epoch,
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

        def get(self, model, key, **_kwargs):  # accept Session.get options (e.g. with_for_update)
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
    stored_cred = {"hash": None, "epoch": 1}

    class FakeCred:
        def __init__(self, id, hash_val, epoch=1):
            self.id = id
            stored_cred["hash"] = hash_val
            stored_cred["epoch"] = epoch

        @property
        def login_password_hash(self):
            return stored_cred["hash"]

        @login_password_hash.setter
        def login_password_hash(self, val):
            stored_cred["hash"] = val

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

        def get(self, model, key, **_kwargs):  # accept Session.get options (e.g. with_for_update)
            if stored_cred["hash"]:
                return FakeCred("default", stored_cred["hash"], stored_cred["epoch"])
            return None

        def add(self, obj):
            stored_cred["hash"] = obj.login_password_hash

        def commit(self):
            pass

    with (
        patch.dict(os.environ, {"MAIL_CORE_DATABASE_URL": "postgresql://test/db", "MAIL_CORE_LOGIN_PASSWORD": "initial_password_1"}),
        patch("mail_core.db.session.get_session_factory", return_value=lambda: FakeSession()),
    ):
        get_login_password_hash()
        assert verify_password("initial_password_1")

        with patch("mail_core.security.auth._persist_db_password_hash", return_value=False):
            with pytest.raises(AuthConfigError, match="failed to persist password to database"):
                change_login_password(current="initial_password_1", new="new_password_fails_to_save")

        # Memory cache and verification must remain unchanged
        assert verify_password("initial_password_1")
        assert not verify_password("new_password_fails_to_save")


def test_auth_db_query_failure_fails_closed_does_not_fallback_to_env():
    """A37: If database is configured but query fails, fail closed (never fallback to env password)."""
    reset_auth_caches()

    class BrokenSession:
        def __enter__(self):
            raise RuntimeError("Database connection refused")

        def __exit__(self, *args):
            return False

    with (
        patch.dict(os.environ, {
            "MAIL_CORE_DATABASE_URL": "postgresql://test/db",
            "MAIL_CORE_LOGIN_PASSWORD": "old_env_fallback_password",
        }),
        patch("mail_core.db.session.get_session_factory", return_value=lambda: BrokenSession()),
    ):
        # Must raise AuthConfigError directly, not fallback to old_env_fallback_password
        with pytest.raises(AuthConfigError, match="failed to query authentication credentials"):
            get_login_password_hash()

        # verify_password must return False, denying access
        assert not verify_password("old_env_fallback_password")


def test_change_password_atomic_commit_and_rollback_on_failure():
    """A37: Password hash and session epoch commit atomically; failure rolls back and keeps old state."""
    reset_auth_caches()
    stored_cred = {"hash": None, "epoch": 1}

    class FakeCred:
        def __init__(self, id, hash_val, epoch=1, session=None):
            self.id = id
            self._hash = hash_val
            self._epoch = epoch
            self._session = session

        @property
        def login_password_hash(self):
            return self._session._pending_hash if (self._session and self._session._pending_hash is not None) else self._hash

        @login_password_hash.setter
        def login_password_hash(self, val):
            if self._session:
                self._session._pending_hash = val
            else:
                self._hash = val

        @property
        def session_epoch(self):
            return self._session._pending_epoch if (self._session and self._session._pending_epoch is not None) else self._epoch

        @session_epoch.setter
        def session_epoch(self, val):
            if self._session:
                self._session._pending_epoch = val
            else:
                self._epoch = val

    should_fail_commit = False

    class FakeSession:
        def __init__(self):
            self._pending_hash = None
            self._pending_epoch = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, *args):
            return False

        def get(self, model, key, **_kwargs):  # accept Session.get options (e.g. with_for_update)
            if stored_cred["hash"]:
                return FakeCred("default", stored_cred["hash"], stored_cred["epoch"], session=self)
            return None

        def add(self, obj):
            self._pending_hash = obj.login_password_hash
            self._pending_epoch = obj.session_epoch

        def commit(self):
            if should_fail_commit:
                raise RuntimeError("DB commit failed")
            if self._pending_hash is not None:
                stored_cred["hash"] = self._pending_hash
            if self._pending_epoch is not None:
                stored_cred["epoch"] = self._pending_epoch

    with (
        patch.dict(os.environ, {
            "MAIL_CORE_DATABASE_URL": "postgresql://test/db",
            "MAIL_CORE_LOGIN_PASSWORD": "valid_initial_pwd",
            "MAIL_CORE_SECRET_KEY": "test_secret_key_12345678901234567890",
        }),
        patch("mail_core.db.session.get_session_factory", return_value=lambda: FakeSession()),
    ):
        get_login_password_hash()
        assert verify_password("valid_initial_pwd")
        cookie_val, _ = issue_session()
        assert read_session(cookie_val) is not None

        # 1. Successful change password atomically updates hash and epoch
        change_login_password(current="valid_initial_pwd", new="new_pwd_1234567")
        assert verify_password("new_pwd_1234567")
        assert not verify_password("valid_initial_pwd")
        assert stored_cred["epoch"] == 2
        # Old session is revoked immediately
        assert read_session(cookie_val) is None

        # 2. Simulated DB failure during next password change
        cookie_val_2, _ = issue_session()
        assert read_session(cookie_val_2) is not None
        should_fail_commit = True

        with pytest.raises(AuthConfigError, match="failed to persist password to database"):
            change_login_password(current="new_pwd_1234567", new="another_pwd_fails")

        # Must retain previous valid password and session
        should_fail_commit = False
        assert verify_password("new_pwd_1234567")
        assert not verify_password("another_pwd_fails")
        assert read_session(cookie_val_2) is not None


def test_cross_process_epoch_revocation_is_bounded_by_cache_ttl():
    """A86: Remote epoch changes apply after the short cache TTL."""
    reset_auth_caches()
    stored_cred = {"hash": "dummy", "epoch": 1}
    fake_time = [100.0]
    query_count = 0
    db_unavailable = False

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
            if db_unavailable:
                raise RuntimeError("Database connection refused")
            return self

        def __exit__(self, *args):
            return False

        def get(self, model, key, **_kwargs):  # accept Session.get options (e.g. with_for_update)
            nonlocal query_count
            query_count += 1
            return FakeCred("default", stored_cred["hash"], stored_cred["epoch"])

        def commit(self):
            pass

    with (
        patch.dict(os.environ, {
            "MAIL_CORE_DATABASE_URL": "postgresql://test/db",
            "MAIL_CORE_SECRET_KEY": "test_secret_key_12345678901234567890",
        }),
        patch("mail_core.db.session.get_session_factory", return_value=lambda: FakeSession()),
        patch("mail_core.security.auth.time.monotonic", side_effect=lambda: fake_time[0]),
    ):
        cookie_val, _ = issue_session()
        assert read_session(cookie_val) is not None
        assert query_count == 1

        # Another process increments epoch directly in DB. The cached epoch remains valid only until TTL expiry.
        stored_cred["epoch"] = 2
        assert read_session(cookie_val) is not None
        assert query_count == 1

        fake_time[0] += _SESSION_EPOCH_CACHE_TTL_SECONDS
        assert read_session(cookie_val) is None
        assert query_count == 2

        current_cookie, _ = issue_session()
        db_unavailable = True
        fake_time[0] += _SESSION_EPOCH_CACHE_TTL_SECONDS
        assert read_session(current_cookie) is None


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

        def get(self, model, key, **_kwargs):  # accept Session.get options (e.g. with_for_update)
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


def test_get_session_epoch_does_not_create_a_missing_credential_row():
    reset_auth_caches()

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, _model, _key):
            return None

        def add(self, _obj):
            raise AssertionError("read path must not add AuthCredential")

        def commit(self):
            raise AssertionError("read path must not commit")

    try:
        with (
            patch.dict(os.environ, {"MAIL_CORE_DATABASE_URL": "postgresql://test/db"}),
            patch("mail_core.db.session.get_session_factory", return_value=lambda: FakeSession()),
        ):
            assert get_session_epoch() == 1
    finally:
        reset_auth_caches()


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes")
def test_password_hash_file_is_private_on_initial_and_update(tmp_path, monkeypatch):
    from stat import S_IMODE

    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "")
    monkeypatch.setenv("MAIL_CORE_LOGIN_PASSWORD", "initial_password_1")
    monkeypatch.setenv("MAIL_CORE_PASSWORD_HASH_PATH", str(tmp_path / "login-password.bcrypt"))
    monkeypatch.setenv("MAIL_CORE_DATA_DIR", "")
    monkeypatch.delenv("MAIL_CORE_LOGIN_PASSWORD_HASH", raising=False)
    reset_auth_caches()

    try:
        password_hash_path = tmp_path / "login-password.bcrypt"
        get_login_password_hash()
        assert S_IMODE(password_hash_path.stat().st_mode) == 0o600

        password_hash_path.chmod(0o644)
        change_login_password(current="initial_password_1", new="new_password_2026")
        assert S_IMODE(password_hash_path.stat().st_mode) == 0o600
    finally:
        reset_auth_caches()


def test_new_password_limit_uses_utf8_byte_length_and_preserves_existing_hash(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "")
    monkeypatch.setenv("MAIL_CORE_LOGIN_PASSWORD", "initial_password_1")
    monkeypatch.delenv("MAIL_CORE_LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("MAIL_CORE_PASSWORD_HASH_PATH", "")
    monkeypatch.setenv("MAIL_CORE_DATA_DIR", "")
    reset_auth_caches()

    try:
        password_at_limit = "é" * 36
        change_login_password(current="initial_password_1", new=password_at_limit)
        stored_hash = get_login_password_hash()
        assert verify_password(password_at_limit)

        with pytest.raises(AuthConfigError, match="72 bytes when encoded as UTF-8"):
            change_login_password(current=password_at_limit, new="é" * 37)

        assert get_login_password_hash() == stored_hash
        assert verify_password(password_at_limit)
    finally:
        reset_auth_caches()


def test_initial_plaintext_password_rejects_more_than_72_utf8_bytes(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_DATABASE_URL", "")
    monkeypatch.setenv("MAIL_CORE_LOGIN_PASSWORD", "é" * 37)
    monkeypatch.delenv("MAIL_CORE_LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("MAIL_CORE_PASSWORD_HASH_PATH", "")
    reset_auth_caches()

    try:
        with pytest.raises(AuthConfigError, match="72 bytes when encoded as UTF-8"):
            get_login_password_hash()
    finally:
        reset_auth_caches()
