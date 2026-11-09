"""Adoption A15 tests: OS file locking, atomic publishing, fail-close integrity."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import bcrypt
import pytest

from mail_core.runtime.bootstrap import (
    INITIAL_PASSWORD_FILE,
    _atomic_write_secret,
    _bootstrap_lock,
    _read_or_create,
    _validate_bcrypt_hash,
    bootstrap_data_dir,
)


def _valid_hash() -> bytes:
    return bcrypt.hashpw(b"test-password", bcrypt.gensalt())


def test_multiprocess_concurrent_bootstrap(tmp_path):
    data_dir = tmp_path / "data"
    worker_script = tmp_path / "worker.py"
    worker_script.write_text(
        """
import json, os, sys
from pathlib import Path
from mail_core.runtime.bootstrap import bootstrap_data_dir

data_dir = sys.argv[1]
env = {}
bootstrap_data_dir(data_dir, env)
print(json.dumps({
    "secret_key": env["MAIL_CORE_SECRET_KEY"],
    "blob_key": env["MAIL_CORE_BLOB_KEY_V1"],
    "backup_key": env["MAIL_CORE_BACKUP_KEY"],
    "hash_path": env["MAIL_CORE_PASSWORD_HASH_PATH"],
}))
""",
        encoding="utf-8",
    )

    src_dir = str(Path(__file__).resolve().parents[2] / "src")
    sub_env = {**os.environ, "PYTHONPATH": src_dir}

    processes = [
        subprocess.Popen(
            [sys.executable, str(worker_script), str(data_dir)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=sub_env,
        )
        for _ in range(4)
    ]

    results = []
    try:
        for p in processes:
            try:
                stdout, stderr = p.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                for q in processes:
                    if q.poll() is None:
                        q.kill()
                for q in processes:
                    q.wait()
                raise
            assert p.returncode == 0, f"Worker process failed: {stderr}"
            results.append(json.loads(stdout.strip()))
    finally:
        for q in processes:
            if q.poll() is None:
                q.kill()
                q.wait()

    assert len(results) == 4
    first = results[0]
    for r in results[1:]:
        assert r == first

    initial_pw = (data_dir / INITIAL_PASSWORD_FILE).read_text(encoding="utf-8").strip()
    hash_bytes = (data_dir / "secrets" / "login-password.bcrypt").read_bytes()
    assert bcrypt.checkpw(initial_pw.encode("utf-8"), hash_bytes)


def test_empty_session_key_fails_close_without_overwrite(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True)
    key_file = secrets_dir / "session.key"
    key_file.write_bytes(b"")

    with pytest.raises(RuntimeError, match="empty or corrupted"):
        bootstrap_data_dir(tmp_path, {})

    # Must fail-close and NEVER overwrite existing file
    assert key_file.read_bytes() == b""


def test_whitespace_only_secret_key_fails_close(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True)
    key_file = secrets_dir / "blob-v1.key"
    key_file.write_text("   \n\t  \n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="empty or corrupted"):
        bootstrap_data_dir(tmp_path, {})

    assert key_file.read_text(encoding="utf-8") == "   \n\t  \n"


def test_empty_bcrypt_hash_fails_close_without_overwrite(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True)
    hash_file = secrets_dir / "login-password.bcrypt"
    hash_file.write_bytes(b"")

    with pytest.raises(RuntimeError, match="invalid or corrupted"):
        bootstrap_data_dir(tmp_path, {})

    assert hash_file.read_bytes() == b""


def test_corrupted_bcrypt_hash_fails_close(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True)
    hash_file = secrets_dir / "login-password.bcrypt"
    hash_file.write_bytes(b"corrupted-hash-that-does-not-start-with-dollar-2")

    with pytest.raises(RuntimeError, match="invalid or corrupted"):
        bootstrap_data_dir(tmp_path, {})


def test_empty_initial_password_file_fails_close(tmp_path):
    pw_file = tmp_path / INITIAL_PASSWORD_FILE
    pw_file.write_text("", encoding="utf-8")

    with pytest.raises(RuntimeError, match="empty or corrupted"):
        bootstrap_data_dir(tmp_path, {})

    # Must not generate a hash from empty password
    assert not (tmp_path / "secrets" / "login-password.bcrypt").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes")
def test_directory_0700_and_all_files_0600(tmp_path):
    bootstrap_data_dir(tmp_path, {})

    secrets_dir = tmp_path / "secrets"
    assert stat.S_IMODE(secrets_dir.stat().st_mode) == 0o700

    secret_files = list(secrets_dir.iterdir())
    assert len(secret_files) >= 4  # session, blob, backup, bcrypt, lock
    for f in secret_files:
        assert stat.S_IMODE(f.stat().st_mode) == 0o600, f"File {f.name} mode is {oct(stat.S_IMODE(f.stat().st_mode))}"

    init_pw = tmp_path / INITIAL_PASSWORD_FILE
    assert stat.S_IMODE(init_pw.stat().st_mode) == 0o600


def test_atomic_write_secret_cleans_up_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "test.key"

    def fail_fsync(_fd):
        raise OSError("simulated fsync disk error")

    monkeypatch.setattr(os, "fsync", fail_fsync)

    with pytest.raises(OSError, match="simulated fsync disk error"):
        _atomic_write_secret(target, b"secret-data\n")

    assert not target.exists()
    # Check that no temporary files remain in target directory
    tmp_files = list(tmp_path.glob(".*tmp*"))
    assert tmp_files == []


def test_bootstrap_lock_reentrancy(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir(parents=True)

    with _bootstrap_lock(secrets_dir):
        # Nested call must not deadlock or raise
        with _bootstrap_lock(secrets_dir):
            pass
