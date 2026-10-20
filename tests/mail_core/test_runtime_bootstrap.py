"""Per-install secret bootstrap for ``python -m mail_core --data-dir``."""

from __future__ import annotations

import base64
import stat
import sys

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

