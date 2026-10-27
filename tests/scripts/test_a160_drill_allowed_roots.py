"""A160: backup-restore drill `rm -rf` allowed roots.

Previously allowed_roots contained the whole repo root, so any
repo-internal directory whose basename matched kkmail-backup-drill*
could be deleted. Allowed roots are now repo/.scratch and system temp.
"""
from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "mail-core-backup-restore-drill.sh"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _shared_key_env() -> dict[str, str]:
    """Env where the drill stops at the key-differ check (after path
    validation, before any deletion), with a sentinel to prove it."""
    shared = base64.b64encode(os.urandom(32)).decode("ascii")
    env = os.environ.copy()
    env["MAIL_CORE_BACKUP_KEY"] = shared
    env["MAIL_CORE_BLOB_KEY_V1"] = shared
    for name in (
        "MAIL_CORE_BACKUP_KEYS",
        "MAIL_CORE_BLOB_KEYS",
        "MAIL_CORE_BACKUP_KEY_VERSION",
        "MAIL_CORE_BLOB_KEY_VERSION",
        "MAIL_CORE_BLOB_ACTIVE_VERSION",
    ):
        env.pop(name, None)
    return env


def _run(out: Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(SCRIPT), str(out)],
        capture_output=True, text=True, env=env, check=False,
    )


def test_a160_allowed_roots_exclude_bare_repo_root():
    text = _text()
    assert 'repo_root / ".scratch"' in text
    block = re.search(r"allowed_roots = \[(.*?)\]", text, re.S)
    assert block, "allowed_roots block must exist"
    assert not re.search(r"^\s*repo_root,\s*$", block.group(1), re.M), (
        "bare repo_root must not be an allowed root"
    )


def test_a160_repo_internal_docs_path_is_refused():
    out = ROOT / "docs" / "kkmail-backup-drill-a160probe"
    result = _run(out, _shared_key_env())
    assert result.returncode == 2
    assert "outside allowed" in result.stderr
    assert not out.exists()


def test_a160_scratch_path_still_allowed(tmp_path):
    out = ROOT / ".scratch" / "kkmail-backup-drill-a160ok"
    out.mkdir(parents=True, exist_ok=True)
    sentinel = out / "preserve.txt"
    sentinel.write_text("keep", encoding="utf-8")
    try:
        result = _run(out, _shared_key_env())
        # Reached the key-differ gate (past path validation), no deletion.
        assert result.returncode == 2
        assert "MAIL_CORE_BACKUP_KEY must differ" in result.stderr
        assert sentinel.read_text(encoding="utf-8") == "keep"
    finally:
        shutil.rmtree(out, ignore_errors=True)
