"""md_format.py 包装脚本测试。用 tmp_path 下真实 git 仓库验证选文件、黑名单、缺二进制、格式漂移。"""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import md_format as mdf


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    )


def _fake_md_kx(tmp_path):
    """造一个假的 md_kx 可执行：把表分隔行归一（幂等），模拟 check/format 行为。"""
    script = (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "path = Path(sys.argv[-1])\n"
        "text = path.read_text(encoding='utf-8')\n"
        "out = text.replace('|------|------|', '|---|---|')\n"
        "if '--check' in sys.argv:\n"
        "    sys.exit(0 if out == text else 1)\n"
        "path.write_text(out, encoding='utf-8')\n"
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    exe = bin_dir / "md_kx"
    exe.write_text(script, encoding="utf-8")
    exe.chmod(0o755)
    return exe


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    (r / "a.md").write_text("|x|y|\n|------|------|\n|1|2|\n", encoding="utf-8")
    (r / "docs" / "archive").mkdir(parents=True)
    (r / "docs" / "archive" / "keep.md").write_text("archived\n", encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-m", "init")
    monkeypatch.setattr(mdf, "REPO_ROOT", r)
    return r


def test_collect_all_excludes_blacklist(repo):
    rels = mdf.collect_all()
    assert "a.md" in rels
    assert not any("docs/archive/" in rel for rel in rels)


def test_collect_changed_includes_untracked(repo):
    (repo / "b.md").write_text("new\n", encoding="utf-8")
    rels = mdf.collect_changed()
    assert "b.md" in rels


def test_format_rejects_blacklist(repo):
    with pytest.raises(mdf.MdFormatError, match="黑名单"):
        mdf.format_paths(["docs/archive/keep.md"])


def test_format_missing_binary(repo, monkeypatch):
    monkeypatch.setattr(mdf, "find_md_kx", lambda: None)
    with pytest.raises(mdf.MdFormatError, match="找不到 md_kx"):
        mdf.format_paths(["a.md"])


def test_format_changes_file(repo, tmp_path, monkeypatch):
    exe = _fake_md_kx(tmp_path)
    monkeypatch.setattr(mdf, "find_md_kx", lambda: str(exe))
    changed = mdf.format_paths(["a.md"])
    assert changed == ["a.md"]
    assert "|---|---|" in (repo / "a.md").read_text(encoding="utf-8")


def test_format_failure_rolls_back_already_formatted(repo, tmp_path, monkeypatch):
    """中途失败：已格式化文件回滚，不留「已格式化未暂存」状态。"""
    bin_dir = tmp_path / "bin_fail"
    bin_dir.mkdir()
    exe = bin_dir / "md_kx"
    exe.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "from pathlib import Path\n"
        "path = Path(sys.argv[-1])\n"
        "if path.name == 'b.md':\n"
        "    sys.exit(2)\n"
        "text = path.read_text(encoding='utf-8')\n"
        "path.write_text(text.replace('|------|------|', '|---|---|'), encoding='utf-8')\n"
    )
    exe.chmod(0o755)
    monkeypatch.setattr(mdf, "find_md_kx", lambda: str(exe))
    (repo / "b.md").write_text("|x|y|\n|------|------|\n|1|2|\n", encoding="utf-8")
    before = (repo / "a.md").read_bytes()

    with pytest.raises(mdf.MdFormatError, match="回滚"):
        mdf.format_paths(["a.md", "b.md"])
    assert (repo / "a.md").read_bytes() == before


def test_check_detects_drift(repo, tmp_path, monkeypatch):
    exe = _fake_md_kx(tmp_path)
    monkeypatch.setattr(mdf, "find_md_kx", lambda: str(exe))
    drift = mdf.format_paths(["a.md"], check=True)
    assert drift == ["a.md"]  # 未格式化，漂移
    # 格式化后无漂移
    mdf.format_paths(["a.md"])
    drift = mdf.format_paths(["a.md"], check=True)
    assert drift == []


def test_main_named_blacklisted_path_errors(repo, capsys):
    """A240：点名黑名单路径须显式报错列出被拒路径，与 format_paths 拒绝语义统一；
    不得静默丢弃后报「无改动」误导用户以为已格式化。"""
    with pytest.raises(SystemExit) as exc:
        mdf.main(["docs/archive/keep.md"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "docs/archive/keep.md" in err and "黑名单" in err


def test_main_mixed_paths_error_lists_only_rejected(repo, capsys):
    """A240：点名混合路径时报错只列黑名单命中者（合法路径不被误列）。"""
    with pytest.raises(SystemExit) as exc:
        mdf.main(["a.md", "docs/archive/keep.md"])
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "docs/archive/keep.md" in err
    assert "a.md，" not in err and "a.md," not in err


def _fake_md_kx_mode(tmp_path, name, script):
    bin_dir = tmp_path / name
    bin_dir.mkdir()
    exe = bin_dir / "md_kx"
    exe.write_text(script, encoding="utf-8")
    exe.chmod(0o755)
    return exe


def test_check_exit1_with_failing_format_is_error_not_drift(repo, tmp_path, monkeypatch):
    """A339：md_kx --check exit 1 且试格式化同样失败（解析错误）时，不得当漂移，
    须按 MdFormatError 抛出并带出 stderr。"""
    exe = _fake_md_kx_mode(tmp_path, "bin_err", (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "print('parse error: broken table', file=sys.stderr)\n"
        "sys.exit(1 if '--check' in sys.argv else 2)\n"
    ))
    monkeypatch.setattr(mdf, "find_md_kx", lambda: str(exe))
    with pytest.raises(mdf.MdFormatError, match="parse error"):
        mdf.format_paths(["a.md"], check=True)


def test_check_exit1_without_content_change_is_error_not_drift(repo, tmp_path, monkeypatch):
    """A339：--check exit 1 但试格式化成功且内容无变化 → 非漂移，按错误抛出。"""
    exe = _fake_md_kx_mode(tmp_path, "bin_nochg", (
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "if '--check' in sys.argv:\n"
        "    print('internal warning state', file=sys.stderr)\n"
        "    sys.exit(1)\n"
        "sys.exit(0)\n"
    ))
    monkeypatch.setattr(mdf, "find_md_kx", lambda: str(exe))
    with pytest.raises(mdf.MdFormatError, match="非格式漂移"):
        mdf.format_paths(["a.md"], check=True)


def test_check_drift_probe_restores_file(repo, tmp_path, monkeypatch):
    """A339：真漂移仍报漂移，且 check 的形态校验试跑不得把文件留在已格式化状态。"""
    exe = _fake_md_kx(tmp_path)
    monkeypatch.setattr(mdf, "find_md_kx", lambda: str(exe))
    before = (repo / "a.md").read_bytes()
    drift = mdf.format_paths(["a.md"], check=True)
    assert drift == ["a.md"]
    assert (repo / "a.md").read_bytes() == before  # check 不写盘


def test_main_check_all_exits_nonzero_on_drift(repo, tmp_path, monkeypatch, capsys):
    exe = _fake_md_kx(tmp_path)
    monkeypatch.setattr(mdf, "find_md_kx", lambda: str(exe))
    with pytest.raises(SystemExit) as exc:
        mdf.main(["--check"])
    assert exc.value.code == 1
    assert "格式漂移" in capsys.readouterr().err
