"""task.py 目录扫描与归档一致性。

通过 monkeypatch 把 task.py 全局路径指向 tmp_path 下临时目录，
不依赖真实仓库结构、不触发 git。
"""
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import pytest
from repo_task import context as ctx
from repo_task import lifecycle, store, worktrees
from repo_task.context import TaskDataError
from repo_task.documents import parse_front_matter, write_front_matter
from repo_task.store import rebuild_index, scan_tasks

pytestmark = pytest.mark.contract


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """把 task.py 全局路径指向 tmp_path 下临时目录，并建空模板目录。"""
    tasks = tmp_path / "docs" / "tasks"
    archive = tmp_path / "docs" / "archive" / "tasks"
    template = tasks / "task_template"
    active_json = tmp_path / "docs" / "tasks_index.json"
    archive_json = tmp_path / "docs" / "archive" / "tasks_index.json"
    tasks.mkdir(parents=True)
    archive.mkdir(parents=True)
    template.mkdir()
    # 模板目录必须含 task.md，scan_tasks 跳过 task_template/
    write_front_matter(
        template / "task.md",
        {"tid": "t000", "slug": "example", "status": "backlog"},
        "模板正文\n",
    )
    monkeypatch.setattr(ctx, "TASKS_DIR", tasks)
    monkeypatch.setattr(ctx, "ARCHIVE_TASKS_DIR", archive)
    monkeypatch.setattr(ctx, "TEMPLATE_DIR", template)
    monkeypatch.setattr(ctx, "ACTIVE_PATH", active_json)
    monkeypatch.setattr(ctx, "ARCHIVE_PATH", archive_json)
    monkeypatch.setattr(ctx, "REPO_ROOT", tmp_path)
    return tmp_path


def _make_task(tasks_dir, tid, slug, status):
    d = tasks_dir / f"{tid}_{slug}"
    d.mkdir()
    write_front_matter(
        d / "task.md",
        {"tid": tid, "slug": slug, "status": status},
        "body\n",
    )
    return d


def test_scan_empty(fake_repo):
    assert scan_tasks() == []


def test_scan_finds_active_task(fake_repo):
    _make_task(ctx.TASKS_DIR, "t001", "alpha", "active")
    rows = scan_tasks()
    assert len(rows) == 1
    assert rows[0]["tid"] == "t001"
    assert rows[0]["status"] == "active"


def test_scan_finds_archived_task(fake_repo):
    _make_task(ctx.ARCHIVE_TASKS_DIR, "t002", "beta", "done")
    rows = scan_tasks()
    assert len(rows) == 1
    assert rows[0]["tid"] == "t002"
    assert rows[0]["status"] == "done"


def test_scan_rejects_invalid_tid(fake_repo):
    _make_task(ctx.TASKS_DIR, "x99", "bad", "backlog")
    with pytest.raises(TaskDataError, match="tid 非法"):
        scan_tasks()


def test_scan_rejects_dirname_mismatch(fake_repo):
    d = ctx.TASKS_DIR / "t003_wrong"
    d.mkdir()
    write_front_matter(
        d / "task.md",
        {"tid": "t003", "slug": "right", "status": "backlog"},
        "x\n",
    )
    with pytest.raises(TaskDataError, match="目录名与 front matter 不符"):
        scan_tasks()


def test_scan_rejects_invalid_status(fake_repo):
    _make_task(ctx.TASKS_DIR, "t004", "gamma", "weird")
    with pytest.raises(TaskDataError, match="status 非法"):
        scan_tasks()


def test_scan_rejects_status_location_mismatch(fake_repo):
    # active 状态出现在归档目录
    _make_task(ctx.ARCHIVE_TASKS_DIR, "t005", "delta", "active")
    with pytest.raises(TaskDataError, match="与所在目录不符"):
        scan_tasks()


def test_scan_detects_dup_tid(fake_repo):
    _make_task(ctx.TASKS_DIR, "t006", "eps", "backlog")
    _make_task(ctx.ARCHIVE_TASKS_DIR, "t006", "eps", "done")
    with pytest.raises(TaskDataError, match="重复 tid"):
        scan_tasks()


def test_scan_orders_by_tid_numerically(fake_repo):
    _make_task(ctx.TASKS_DIR, "t010", "ten", "backlog")
    _make_task(ctx.TASKS_DIR, "t002", "two", "backlog")
    _make_task(ctx.TASKS_DIR, "t100", "hundred", "backlog")
    rows = scan_tasks()
    tids = [r["tid"] for r in rows]
    assert tids == ["t002", "t010", "t100"]


def test_rebuild_index_splits_active_archive(fake_repo):
    _make_task(ctx.TASKS_DIR, "t001", "alpha", "backlog")
    _make_task(ctx.TASKS_DIR, "t002", "beta", "active")
    _make_task(ctx.ARCHIVE_TASKS_DIR, "t003", "gamma", "done")
    rebuild_index()
    active = json.loads(ctx.ACTIVE_PATH.read_text(encoding="utf-8"))
    archive = json.loads(ctx.ARCHIVE_PATH.read_text(encoding="utf-8"))
    assert [t["tid"] for t in active["tasks"]] == ["t001", "t002"]
    assert [t["tid"] for t in archive["tasks"]] == ["t003"]
    assert active["authority"] == "docs/tasks/{tid}_{slug}/task.md front matter"
    assert archive["authority"] == (
        "docs/archive/tasks/{tid}_{slug}/task.md front matter"
    )


def test_rebuild_index_uses_utf8_and_lf(fake_repo):
    _make_task(ctx.TASKS_DIR, "t001", "alpha", "backlog")
    rebuild_index()
    raw = ctx.ACTIVE_PATH.read_bytes()
    assert b"\r\n" not in raw
    # ensure_ascii=False：中文不转义
    text = raw.decode("utf-8")
    assert '"tasks"' in text


def test_unlink_managed_env_links_only_removes_script_links(fake_repo):
    source = fake_repo / ".env"
    source.write_text("secret", encoding="utf-8")
    worktree = fake_repo / "worktree"
    worktree.mkdir()

    assert worktrees.link_local_env(worktree) == [".env"]
    managed = worktree / ".env"
    assert worktrees.is_managed_env_link(worktree, managed)

    nested = worktree / "config"
    nested.mkdir()
    other = fake_repo / "other.env"
    other.write_text("other", encoding="utf-8")
    unmanaged = nested / ".env"
    unmanaged.symlink_to(other)
    assert not worktrees.is_managed_env_link(worktree, unmanaged)

    worktrees.unlink_managed_env_links(worktree)
    assert not managed.is_symlink()
    assert unmanaged.is_symlink()


def test_managed_env_link_stays_identifiable_after_source_removed(fake_repo):
    source = fake_repo / ".env"
    source.write_text("secret", encoding="utf-8")
    worktree = fake_repo / "worktree"
    worktree.mkdir()
    worktrees.link_local_env(worktree)
    source.unlink()

    link = worktree / ".env"
    assert worktrees.is_managed_env_link(worktree, link)
    worktrees.unlink_managed_env_links(worktree)
    assert not link.is_symlink()


def _make_managed_link(fake_repo, worktree, rel):
    import os

    src = fake_repo / rel
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("x", encoding="utf-8")
    dst = worktree / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.symlink_to(os.path.relpath(src, dst.parent))
    return dst


def test_unlink_managed_env_links_prunes_skip_dirs(fake_repo):
    """A208: unlink 走树须原地剪枝 skip 目录，不得全量走树。"""
    worktree = fake_repo / "worktree"
    worktree.mkdir()
    top = _make_managed_link(fake_repo, worktree, ".env")
    in_node_modules = _make_managed_link(
        fake_repo, worktree, "node_modules/.env"
    )
    in_git = _make_managed_link(fake_repo, worktree, ".git/.env")
    in_venv = _make_managed_link(fake_repo, worktree, ".venv/.env")
    for link in (top, in_node_modules, in_git, in_venv):
        assert worktrees.is_managed_env_link(worktree, link)

    worktrees.unlink_managed_env_links(worktree)

    assert not top.is_symlink()  # 正常目录仍清理
    # 剪枝目录内的链接不被访问（保留原样），证明没有全量走树
    assert in_node_modules.is_symlink()
    assert in_git.is_symlink()
    assert in_venv.is_symlink()


def test_skip_dirs_is_shared_constant():
    """A208: link/unlink 共用同一 skip 集合，且含 .git。"""
    assert ".git" in worktrees.SKIP_DIRS
    assert "node_modules" in worktrees.SKIP_DIRS
    assert ".venv" in worktrees.SKIP_DIRS


def test_link_local_env_prunes_skip_dirs_during_walk(fake_repo, monkeypatch):
    """A260: 收集源须在遍历期剪枝，而不是 rglob 全树后按结果过滤。"""
    import os

    (fake_repo / "app").mkdir()
    (fake_repo / "app" / ".env").write_text("a", encoding="utf-8")
    nm = fake_repo / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / ".env").write_text("nm", encoding="utf-8")
    worktree = fake_repo / "worktree"
    worktree.mkdir()

    visited_roots = []
    real_walk = os.walk

    def counting_walk(*args, **kwargs):
        for root, dirs, files in real_walk(*args, **kwargs):
            visited_roots.append(Path(root))
            yield root, dirs, files

    monkeypatch.setattr(os, "walk", counting_walk)
    linked = worktrees.link_local_env(worktree)

    assert linked == ["app/.env"]
    assert visited_roots, "link_local_env 应经 os.walk 遍历以便遍历期剪枝"
    assert not any("node_modules" in root.parts for root in visited_roots)


def test_link_local_env_skips_symlink_source_resolving_outside_repo(fake_repo):
    """A260: .env 符号链接源解析出仓时必须跳过，不得链入 worktree。"""
    outside_dir = Path(str(fake_repo) + "_outside")
    outside_dir.mkdir()
    outside = outside_dir / "secret.env"
    outside.write_text("outside", encoding="utf-8")
    sub = fake_repo / "sub"
    sub.mkdir()
    (sub / ".env").symlink_to(outside)
    worktree = fake_repo / "worktree"
    worktree.mkdir()

    assert worktrees.link_local_env(worktree) == []
    assert not (worktree / "sub" / ".env").is_symlink()


def test_link_local_env_allows_symlink_source_resolving_inside_repo(fake_repo):
    """A260: 符号链接源解析仍在仓内时照常链入。"""
    real = fake_repo / "real"
    real.mkdir()
    (real / ".env").write_text("in", encoding="utf-8")
    alias = fake_repo / "alias"
    alias.mkdir()
    (alias / ".env").symlink_to(real / ".env")
    worktree = fake_repo / "worktree"
    worktree.mkdir()

    linked = worktrees.link_local_env(worktree)
    assert "alias/.env" in linked
    assert "real/.env" in linked


def test_close_task_rolls_back_when_move_fails(fake_repo, monkeypatch):
    """归档移动失败时 front matter 回滚，避免「已写 done、目录未归档」死锁。"""
    import argparse

    d = _make_task(ctx.TASKS_DIR, "t001", "alpha", "active")

    def boom(src, dst):
        raise OSError("模拟移动失败")

    monkeypatch.setattr(lifecycle.shutil, "move", boom)
    monkeypatch.setattr(lifecycle, "require_own_task_worktree", lambda fm: None)
    # fake_repo 非 git 仓库，worktree_paths 会抛 fail-closed；模拟无登记 worktree
    monkeypatch.setattr(lifecycle, "in_own_task_worktree", lambda fm: False)
    monkeypatch.setattr(worktrees, "worktree_paths", lambda: {})
    with pytest.raises(SystemExit, match="归档移动失败"):
        lifecycle._close_task(argparse.Namespace(tid="t001"), "done", None)
    fm, _ = parse_front_matter(d / "task.md")
    assert fm["status"] == "active"  # 已回滚
    assert d.is_dir()  # 目录仍在活跃区


def test_list_is_readonly_by_default(fake_repo, capsys):
    """list 只罗列，不写派生 index。"""
    import argparse

    _make_task(ctx.TASKS_DIR, "t001", "alpha", "backlog")
    assert not ctx.ACTIVE_PATH.exists()
    lifecycle.cmd_list(argparse.Namespace(status=None, rebuild=False, ref=None))
    capsys.readouterr()
    assert not ctx.ACTIVE_PATH.exists()


def test_list_rebuild_writes_index(fake_repo, capsys, monkeypatch):
    import argparse

    _make_task(ctx.TASKS_DIR, "t001", "alpha", "backlog")
    monkeypatch.setattr(lifecycle, "require_primary_worktree", lambda: None)
    lifecycle.cmd_list(argparse.Namespace(status=None, rebuild=True, ref=None))
    out = capsys.readouterr().out
    assert ctx.ACTIVE_PATH.exists()
    assert "index rebuilt" in out
