"""A36: git_common_dir 子进程异常须与 git_ops 统一包装口径一致。

TimeoutExpired（非 OSError）与 FileNotFoundError 不得裸穿透到 CLI 顶层
（cli.py 只捕 TaskDataError/OSError）；本地 catch 后转 OSError 并附上下文。
"""
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pytest

from repo_task import locks

pytestmark = pytest.mark.contract


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )


def test_git_common_dir_real_repo(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    result = locks.git_common_dir(tmp_path)
    assert result == (tmp_path / ".git").resolve()


def test_git_common_dir_timeout_becomes_oserror(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=30)

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(OSError) as excinfo:
        locks.git_common_dir(tmp_path)
    assert not isinstance(excinfo.value, subprocess.TimeoutExpired)
    assert "无法解析 git 公共目录" in str(excinfo.value)


def test_git_common_dir_missing_git_becomes_contextual_oserror(tmp_path, monkeypatch):
    def boom(*_args, **_kwargs):
        raise FileNotFoundError(2, "No such file or directory", "git")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(OSError) as excinfo:
        locks.git_common_dir(tmp_path)
    assert "无法解析 git 公共目录" in str(excinfo.value)
    assert "git" in str(excinfo.value)


def test_git_common_lock_roundtrip_real_repo(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    with locks.git_common_lock(tmp_path, "probe.lock"):
        assert (tmp_path / ".git" / "probe.lock").is_file()
