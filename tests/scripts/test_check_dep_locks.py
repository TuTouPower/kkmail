"""Tests for production dependency lock consistency and build gate verification."""

import re
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
    # `--check` is an offline self-consistency check; it does not shell out
    # to `uv` or touch the network. The running interpreter is passed by
    # absolute path, so no PATH manipulation is needed.
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


def test_build_sidecar_smoke_checks_binary_before_copy():
    """A305: the built sidecar must pass a runnable smoke check before the
    copy into desktop resources; a broken binary must abort the build."""
    sidecar_script = (ROOT / "scripts" / "build-sidecar.sh").read_text(encoding="utf-8")
    smoke = sidecar_script.index('"dist/kkmail-backend${EXE}" --help')
    copy = sidecar_script.index('cp "dist/kkmail-backend${EXE}"')
    assert smoke < copy, "smoke check must run before copying into desktop resources"


def _load_dep_module(monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_dep_locks_under_test", ROOT / "scripts" / "check_dep_locks.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_check_is_offline_no_recompile(monkeypatch):
    """--check 不得联网重解析，否则上游发版必然反复漂移（t078 AC-003）。"""

    module = _load_dep_module(monkeypatch)

    def _boom(*args, **kwargs):
        raise AssertionError("--check must not call uv pip compile")

    monkeypatch.setattr(module, "run_compile", _boom)
    monkeypatch.setattr(sys, "argv", ["check_dep_locks.py", "--check"])
    assert module.main() == 0


def test_check_rejects_lock_missing_hash(monkeypatch, tmp_path):
    """离线自洽校验仍须拒绝缺 hash 的 lock（t078 AC-004，能力不削弱）。

    从真实 lock 复制并仅删去一行 hash：其余 9 个依赖仍全部固定，因此
    「未固定」不会成为噪声，失败原因唯一是 hash 缺失。
    """

    module = _load_dep_module(monkeypatch)
    lines = (ROOT / "requirements-mail-core.lock").read_text(encoding="utf-8").splitlines()
    pin_idx = next(
        i for i, line in enumerate(lines) if re.match(r"\A[A-Za-z0-9_.-]+==", line.strip())
    )
    # 删除该 pin 下全部 hash 续行（每个包有 2 个），否则另一条 hash 会
    # 让该包仍被视为「已签名」，错误原因被掩盖。
    j = pin_idx + 1
    while j < len(lines) and lines[j].strip().startswith("--hash="):
        del lines[j]
    broken = tmp_path / "broken.lock"
    broken.write_text("\n".join(lines) + "\n", encoding="utf-8")

    errors = module.verify_lock_offline(broken, module.TXT_FILE)
    assert any("has no sha256 hash" in e for e in errors), errors

    monkeypatch.setattr(module, "LOCK_FILE", broken)
    monkeypatch.setattr(sys, "argv", ["check_dep_locks.py", "--check"])
    assert module.main() != 0


def test_upstream_release_does_not_invalidate_older_lock(monkeypatch, tmp_path):
    """lock 非「当下最新」但满足下界即通过：上游发版不触发漂移（t078 AC-003）。"""

    module = _load_dep_module(monkeypatch)
    original = (ROOT / "requirements-mail-core.lock").read_text(encoding="utf-8")
    older = re.sub(r"fastapi==[^\s\\]+", "fastapi==0.115.0", original)
    older_lock = tmp_path / "older.lock"
    older_lock.write_text(older, encoding="utf-8")
    assert module.verify_lock_offline(older_lock, module.TXT_FILE) == []


def test_lock_below_declared_floor_rejected(monkeypatch, tmp_path):
    """lock 版本低于 .txt 下界必须被拒绝（t078 AC-004，负向 true-positive）。"""

    module = _load_dep_module(monkeypatch)
    original = (ROOT / "requirements-mail-core.lock").read_text(encoding="utf-8")
    below = re.sub(r"fastapi==[^\s\\]+", "fastapi==0.100.0", original)
    below_lock = tmp_path / "below.lock"
    below_lock.write_text(below, encoding="utf-8")
    errors = module.verify_lock_offline(below_lock, module.TXT_FILE)
    assert any("does not satisfy" in e for e in errors), errors


def test_compound_constraint_upper_bound_enforced(monkeypatch, tmp_path):
    """复合约束的上界不得被逗号截断静默丢弃（t078 code f004）。"""

    module = _load_dep_module(monkeypatch)
    txt = tmp_path / "requirements.txt"
    txt.write_text("foo>=1.2,<2.0\n", encoding="utf-8")
    lock = tmp_path / "requirements.lock"
    lock.write_text(
        "foo==2.5 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n",
        encoding="utf-8",
    )
    errors = module.verify_lock_offline(lock, txt)
    assert any("does not satisfy" in e for e in errors), errors
