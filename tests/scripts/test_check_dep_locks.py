"""Tests for production dependency lock consistency and build gate verification."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def test_mail_core_lock_exists_and_contains_hashes():
    lock_file = ROOT / "requirements-mail-core.lock"
    assert lock_file.is_file(), "requirements-mail-core.lock must exist"

    content = lock_file.read_text(encoding="utf-8")
    assert "--hash=sha256:" in content, "Lockfile must contain sha256 hashes"
    for pkg in ("fastapi==", "sqlalchemy==", "pydantic==", "uvicorn==", "alembic=="):
        assert pkg in content, f"Lockfile must pin {pkg}"


def test_check_dep_locks_script_passes():
    script = ROOT / "scripts" / "check_dep_locks.py"
    proc = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"check_dep_locks.py --check failed: {proc.stderr}\n{proc.stdout}"
    assert "synchronized" in proc.stdout


def test_dockerfiles_use_require_hashes():
    df_core = (ROOT / "Dockerfile.mail-core").read_text(encoding="utf-8")
    assert "requirements-mail-core.lock" in df_core
    assert "--require-hashes" in df_core

    df_backup = (ROOT / "Dockerfile.mail-core-backup").read_text(encoding="utf-8")
    assert "requirements-mail-core.lock" in df_backup
    assert "--require-hashes" in df_backup


def test_build_sidecar_script_includes_gate():
    sidecar_script = (ROOT / "scripts" / "build-sidecar.sh").read_text(encoding="utf-8")
    assert "check_dep_locks.py --check" in sidecar_script
    assert "backend-build-info.json" in sidecar_script
