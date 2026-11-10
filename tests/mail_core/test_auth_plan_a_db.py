"""Unit + real-PostgreSQL tests for Plan A: login password hash and session epoch.

The five database cases run against real PostgreSQL via ``get_session_factory()``
and real ``AuthCredential`` rows; they are skipped without
``MAIL_CORE_DATABASE_URL`` (unit quick mode). Pure unit cases (file permissions,
72-byte password limit, missing-credential fail-closed) stay unit-runnable.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from unittest.mock import patch

import bcrypt
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session as OrmSession, sessionmaker
from sqlalchemy.pool import NullPool

from mail_core.security.auth import (
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

requires_pg = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


# Retired FakeSession/BrokenSession suite: the five cases below previously used
# in-process FakeSession/BrokenSession doubles plus dicts to impersonate
# PostgreSQL commits, rollbacks, outages and cross-process epoch reads. Such
# doubles cannot prove real transactional/persistence semantics: a dict has no
# transaction boundary, no rollback, no durable commit and no real fail-closed
# DB error. Per this repo's TDD rule they are NOT edited in place (no flipping an
# old assertion inside the implementation); each old body is removed wholesale
# and replaced by a real-PG implementation over get_session_factory() and real
# AuthCredential rows. The earlier A13 retirement note still applies: true
# two-process revocation lives in
# tests/mail_core/test_a13_session_revocation_multiprocess.py; here
# reset_auth_caches() only simulates a process holding a stale in-memory epoch,
# with the real DB row as the sole authority. isolated_runtime TRUNCATEs before
# and after each case, so the 'default' row a case writes never leaks across
# cases; no test TRUNCATEs the database itself.


def _credential_row():
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import AuthCredential

    Session = get_session_factory()
    with Session() as session:
        cred = session.get(AuthCredential, "default")
        if cred is None:
            return None
        return cred.login_password_hash, int(cred.session_epoch)


def _seed_credential(password: str, epoch: int = 1) -> None:
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import AuthCredential

    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    Session = get_session_factory()
    with Session() as session:
        cred = session.get(AuthCredential, "default")
        if cred is None:
            session.add(
                AuthCredential(
                    id="default",
                    login_password_hash=password_hash,
                    session_epoch=epoch,
                )
            )
        else:
            cred.login_password_hash = password_hash
            cred.session_epoch = epoch
        session.commit()


@contextmanager
def _injected_commit_failure():
    """Raise from SQLAlchemy's before_commit so a real PG transaction cannot commit."""
    armed = {"value": False}

    def before_commit(session):
        # before_commit also fires on nested SAVEPOINT releases (used by
        # try_notify_session_revocation); only the outermost real commit must
        # fail, so the transaction rolls back as a whole.
        if armed["value"] and session.get_nested_transaction() is None:
            raise RuntimeError("injected real-PG commit failure")

    event.listen(OrmSession, "before_commit", before_commit)
    try:
        yield armed
    finally:
        armed["value"] = False
        event.remove(OrmSession, "before_commit", before_commit)


@requires_pg
def test_auth_plan_a_database_persistence(monkeypatch):
    """Real PG: first boot bootstraps a row, a change commits, DB stays authoritative."""
    monkeypatch.setenv("MAIL_CORE_LOGIN_PASSWORD", "initial_env_password")
    monkeypatch.delenv("MAIL_CORE_LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("MAIL_CORE_PASSWORD_HASH_PATH", "")
    reset_auth_caches()
    try:
        # isolated_runtime left the table empty; get_login_password_hash()
        # bootstraps from env and persists a real AuthCredential row.
        h1 = get_login_password_hash()
        assert bcrypt.checkpw(b"initial_env_password", h1)
        stored = _credential_row()
        assert stored is not None
        db_hash_1, epoch_1 = stored
        assert bcrypt.checkpw(b"initial_env_password", db_hash_1.encode("utf-8"))
        assert epoch_1 == 1
        assert verify_password("initial_env_password")

        change_login_password(current="initial_env_password", new="new_changed_password_2026")
        db_hash_2, epoch_2 = _credential_row()
        assert bcrypt.checkpw(b"new_changed_password_2026", db_hash_2.encode("utf-8"))
        assert epoch_2 == 2
        assert verify_password("new_changed_password_2026")
        assert not verify_password("initial_env_password")

        # Simulate a container restart: env still carries the OLD password, but
        # the DB row is authoritative and must win on the next read.
        reset_auth_caches()
        h2 = get_login_password_hash()
        assert bcrypt.checkpw(b"new_changed_password_2026", h2)
        assert verify_password("new_changed_password_2026")
        assert not verify_password("initial_env_password")
    finally:
        reset_auth_caches()


@requires_pg
def test_change_login_password_fails_closed_on_db_error(monkeypatch):
    """Real PG: a failed commit fails closed; old password and epoch survive the rollback."""
    monkeypatch.setenv("MAIL_CORE_LOGIN_PASSWORD", "initial_password_1")
    monkeypatch.delenv("MAIL_CORE_LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("MAIL_CORE_PASSWORD_HASH_PATH", "")
    reset_auth_caches()
    try:
        _seed_credential("initial_password_1", epoch=1)
        assert verify_password("initial_password_1")
        hash_before, epoch_before = _credential_row()

        with _injected_commit_failure() as armed:
            armed["value"] = True
            with pytest.raises(AuthConfigError, match="failed to persist password to database"):
                change_login_password(current="initial_password_1", new="new_password_fails_to_save")
            armed["value"] = False

        # No half-written state: the real transaction rolled back both columns.
        hash_after, epoch_after = _credential_row()
        assert hash_after == hash_before
        assert epoch_after == epoch_before
        assert verify_password("initial_password_1")
        assert not verify_password("new_password_fails_to_save")
    finally:
        reset_auth_caches()


@requires_pg
def test_auth_db_query_failure_fails_closed_does_not_fallback_to_env(monkeypatch):
    """Real PG: an unreachable DB fails closed and never falls back to the env password.

    A dead URL is handed to production via ``get_session_factory`` as a REAL
    SQLAlchemy Engine/sessionmaker (not a FakeSession), so the query failure is
    a genuine connection error. A87: verify_password propagates AuthConfigError
    instead of disguising the outage as a wrong password.
    """
    monkeypatch.setenv("MAIL_CORE_LOGIN_PASSWORD", "old_env_fallback_password")
    monkeypatch.delenv("MAIL_CORE_LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("MAIL_CORE_PASSWORD_HASH_PATH", "")
    reset_auth_caches()

    dead_url = "postgresql+psycopg://kkmail:kkmail@127.0.0.1:1/kkmail_test_dead"
    dead_engine = create_engine(dead_url, poolclass=NullPool, connect_args={"connect_timeout": 2})
    dead_sessionmaker = sessionmaker(bind=dead_engine)
    try:
        with patch("mail_core.db.session.get_session_factory", return_value=dead_sessionmaker):
            with pytest.raises(AuthConfigError, match="failed to query authentication credentials"):
                get_login_password_hash()
            with pytest.raises(AuthConfigError, match="failed to query authentication credentials"):
                verify_password("old_env_fallback_password")
    finally:
        dead_engine.dispose()
        reset_auth_caches()


@requires_pg
def test_change_password_atomic_commit_and_rollback_on_failure(monkeypatch):
    """Real PG: hash+epoch commit atomically; a failed commit rolls both back."""
    monkeypatch.setenv("MAIL_CORE_SECRET_KEY", "auth-plan-a-atomic-secret-key-1234567890")
    monkeypatch.setenv("MAIL_CORE_LOGIN_PASSWORD", "valid_initial_pwd")
    monkeypatch.delenv("MAIL_CORE_LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("MAIL_CORE_PASSWORD_HASH_PATH", "")
    reset_auth_caches()
    try:
        _seed_credential("valid_initial_pwd", epoch=1)
        assert verify_password("valid_initial_pwd")
        cookie_val, _ = issue_session()
        assert read_session(cookie_val) is not None

        # 1. Successful change: hash and epoch move together in one real commit.
        change_login_password(current="valid_initial_pwd", new="new_pwd_1234567")
        hash_ok, epoch_ok = _credential_row()
        assert bcrypt.checkpw(b"new_pwd_1234567", hash_ok.encode("utf-8"))
        assert epoch_ok == 2
        assert verify_password("new_pwd_1234567")
        assert not verify_password("valid_initial_pwd")
        assert read_session(cookie_val) is None

        # 2. A later change whose commit fails must roll BOTH columns back.
        cookie_val_2, _ = issue_session()
        assert read_session(cookie_val_2) is not None
        with _injected_commit_failure() as armed:
            armed["value"] = True
            with pytest.raises(AuthConfigError, match="failed to persist password to database"):
                change_login_password(current="new_pwd_1234567", new="another_pwd_fails")
            armed["value"] = False

        hash_after, epoch_after = _credential_row()
        assert hash_after == hash_ok
        assert epoch_after == epoch_ok
        assert verify_password("new_pwd_1234567")
        assert not verify_password("another_pwd_fails")
        assert read_session(cookie_val_2) is not None
    finally:
        reset_auth_caches()


@requires_pg
def test_session_epoch_persisted_in_database_and_invalidates_across_processes(monkeypatch):
    """Real PG: epoch is durable; invalidate_all_sessions commits, stale caches re-read DB."""
    monkeypatch.setenv("MAIL_CORE_SECRET_KEY", "auth-plan-a-epoch-secret-key-1234567890")
    monkeypatch.setenv("MAIL_CORE_LOGIN_PASSWORD", "epoch_seed_password")
    monkeypatch.delenv("MAIL_CORE_LOGIN_PASSWORD_HASH", raising=False)
    monkeypatch.setenv("MAIL_CORE_PASSWORD_HASH_PATH", "")
    reset_auth_caches()
    try:
        _seed_credential("epoch_seed_password", epoch=1)

        cookie_val, csrf = issue_session()
        assert cookie_val is not None
        session_data = read_session(cookie_val)
        assert session_data is not None
        assert session_data["epoch"] == 1
        assert session_data["csrf"] == csrf

        invalidate_all_sessions()
        _, epoch_after_invalidate = _credential_row()
        assert epoch_after_invalidate == 2
        assert read_session(cookie_val) is None

        cookie_val_2, csrf_2 = issue_session()
        session_data_2 = read_session(cookie_val_2)
        assert session_data_2 is not None
        assert session_data_2["epoch"] == 2
        assert session_data_2["csrf"] == csrf_2

        # Simulate a process that never got the NOTIFY and holds a stale
        # in-memory epoch: read_session must re-query the authoritative DB row.
        reset_auth_caches()
        assert read_session(cookie_val) is None
        assert read_session(cookie_val_2) is not None
    finally:
        reset_auth_caches()


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_a13_missing_credential_record_fails_closed():
    """A13 (real PostgreSQL): a missing credential row fails closed.

    Replaces the former FakeSession version; the semantics are unchanged. With
    MAIL_CORE_DATABASE_URL configured but no auth_credentials row,
    get_session_epoch() must raise AuthConfigError instead of returning the
    in-process default epoch 1, and the read path must not create a row. The
    per-test TRUNCATE in isolated_runtime supplies the empty table and cleans
    up afterwards; this test only ever reads the single 'default' row it owns.
    """
    reset_auth_caches()
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import AuthCredential

    Session = get_session_factory()
    try:
        with Session() as session:
            assert session.get(AuthCredential, "default") is None

        with pytest.raises(
            AuthConfigError, match="auth credential record missing in database"
        ):
            get_session_epoch()

        # The read path must not have inserted a credential row.
        with Session() as session:
            assert session.get(AuthCredential, "default") is None
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
