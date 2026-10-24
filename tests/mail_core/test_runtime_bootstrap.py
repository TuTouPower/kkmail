"""Per-install secret bootstrap for ``python -m mail_core --data-dir``."""

from __future__ import annotations

import base64
import logging
import os
import stat
import sys
from pathlib import Path

import bcrypt
import pytest

from mail_core.runtime.bootstrap import (
    INITIAL_PASSWORD_FILE,
    _read_or_create,
    bootstrap_data_dir,
    clear_initial_password,
)


def test_generates_and_persists_secrets(tmp_path):
    env: dict[str, str] = {}
    bootstrap_data_dir(tmp_path, env)
    assert len(env["MAIL_CORE_SECRET_KEY"]) == 64
    assert len(base64.b64decode(env["MAIL_CORE_BLOB_KEY_V1"])) == 32
    assert env["MAIL_CORE_BACKUP_KEY"] != env["MAIL_CORE_BLOB_KEY_V1"]
    assert env["MAIL_CORE_BLOB_ROOT"] == str(tmp_path / "blobs")
    initial = (tmp_path / INITIAL_PASSWORD_FILE).read_text().strip()
    hashed = (tmp_path / "secrets" / "login-password.bcrypt").read_bytes()
    assert bcrypt.checkpw(initial.encode(), hashed)

    env2: dict[str, str] = {}
    bootstrap_data_dir(tmp_path, env2)
    for k in ("MAIL_CORE_SECRET_KEY", "MAIL_CORE_BLOB_KEY_V1", "MAIL_CORE_BACKUP_KEY"):
        assert env2[k] == env[k], k
    assert (tmp_path / "secrets" / "login-password.bcrypt").read_bytes() == hashed


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_secret_files_are_private(tmp_path):
    bootstrap_data_dir(tmp_path, {})
    for f in (tmp_path / "secrets").iterdir():
        assert stat.S_IMODE(f.stat().st_mode) == 0o600, f


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_existing_secret_files_are_restricted_without_changing_values(tmp_path):
    original_env: dict[str, str] = {}
    bootstrap_data_dir(tmp_path, original_env)
    secret_files = [*(tmp_path / "secrets").iterdir(), tmp_path / INITIAL_PASSWORD_FILE]
    original_contents = {path: path.read_bytes() for path in secret_files}
    for path in secret_files:
        path.chmod(0o644)

    restored_env: dict[str, str] = {}
    bootstrap_data_dir(tmp_path, restored_env)

    assert restored_env["MAIL_CORE_SECRET_KEY"] == original_env["MAIL_CORE_SECRET_KEY"]
    for path in secret_files:
        assert path.read_bytes() == original_contents[path]
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_existing_secret_file_permission_failure_warns_and_continues(tmp_path, monkeypatch, caplog):
    bootstrap_data_dir(tmp_path, {})
    target = tmp_path / "secrets" / "session.key"
    real_chmod = os.chmod

    def chmod(path, mode):
        if Path(path) == target:
            raise PermissionError("permission denied")
        real_chmod(path, mode)

    monkeypatch.setattr("mail_core.runtime.bootstrap.os.chmod", chmod)
    caplog.set_level(logging.WARNING, logger="mail_core.runtime.bootstrap")

    env: dict[str, str] = {}
    bootstrap_data_dir(tmp_path, env)

    assert env["MAIL_CORE_SECRET_KEY"] == target.read_text().strip()
    assert "could not restrict secret file permissions" in caplog.text
    assert str(target) in caplog.text


def test_env_wins_and_no_password_generated(tmp_path):
    env = {"MAIL_CORE_SECRET_KEY": "x" * 64, "MAIL_CORE_LOGIN_PASSWORD": "operator-set-pw"}
    bootstrap_data_dir(tmp_path, env)
    assert env["MAIL_CORE_SECRET_KEY"] == "x" * 64
    assert not (tmp_path / INITIAL_PASSWORD_FILE).exists()
    assert "MAIL_CORE_PASSWORD_HASH_PATH" not in env


def test_clear_initial_password(tmp_path):
    bootstrap_data_dir(tmp_path, {})
    clear_initial_password(tmp_path)
    assert not (tmp_path / INITIAL_PASSWORD_FILE).exists()
    clear_initial_password(tmp_path)  # idempotent


def test_read_or_create_concurrent_race_eliminated(tmp_path):
    import concurrent.futures
    import uuid

    target_file = tmp_path / "secrets" / "race.key"

    def worker():
        return _read_or_create(target_file, lambda: str(uuid.uuid4()))

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(lambda _: worker(), range(16)))

    # All threads must get the exact same secret value
    assert len(set(results)) == 1
    assert target_file.read_text().strip() == results[0]

