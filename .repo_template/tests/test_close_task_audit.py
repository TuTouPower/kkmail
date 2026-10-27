"""A48: finish/drop (and edit) must leave an append_audit record like
rewind/purge do; audit failure after archiving is reported, not silent."""
import argparse
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from repo_task import context as ctx
from repo_task import lifecycle
from repo_task.documents import parse_front_matter, write_front_matter


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    tasks = tmp_path / "docs" / "tasks"
    archive = tmp_path / "docs" / "archive" / "tasks"
    tasks.mkdir(parents=True)
    archive.mkdir(parents=True)
    for tid, slug, status in (("t001", "alpha", "backlog"), ("t002", "beta", "active")):
        d = tasks / f"{tid}_{slug}"
        d.mkdir()
        write_front_matter(
            d / "task.md",
            {"tid": tid, "slug": slug, "title": slug, "status": status,
             "branch": "", "worktree": "", "review_level": "full",
             "diff_anchor": "", "depends_on": "", "conflicts_with": "", "note": ""},
            "body\n",
        )
    monkeypatch.setattr(ctx, "TASKS_DIR", tasks)
    monkeypatch.setattr(ctx, "ARCHIVE_TASKS_DIR", archive)
    monkeypatch.setattr(ctx, "TEMPLATE_DIR", tasks / "task_template")
    monkeypatch.setattr(ctx, "ACTIVE_PATH", tmp_path / "docs" / "tasks_index.json")
    monkeypatch.setattr(ctx, "ARCHIVE_PATH", tmp_path / "docs" / "archive" / "tasks_index.json")
    monkeypatch.setattr(ctx, "AUDIT_PATH", tmp_path / "docs" / "archive" / "tasks_audit.log")
    monkeypatch.setattr(ctx, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(lifecycle, "require_primary_worktree", lambda: None)
    monkeypatch.setattr(lifecycle, "require_own_task_worktree", lambda fm: None)
    monkeypatch.setattr(lifecycle, "remove_worktree", lambda *a, **kw: (True, "removed"))
    monkeypatch.setattr(lifecycle, "in_own_task_worktree", lambda fm: False)
    monkeypatch.setattr(lifecycle, "task_effective_state", lambda *a, **kw: None)
    return tmp_path


def _audit_text(tmp_path):
    p = tmp_path / "docs" / "archive" / "tasks_audit.log"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def test_drop_writes_audit(fake_repo):
    lifecycle.cmd_drop(argparse.Namespace(tid="t001", reason="obsolete"))
    text = _audit_text(fake_repo)
    assert "drop" in text and "tid=t001" in text and "to=dropped" in text
    assert "obsolete" in text


def test_finish_writes_audit(fake_repo, monkeypatch):
    monkeypatch.setattr(lifecycle, "in_own_task_worktree", lambda fm: True)
    lifecycle.cmd_finish(argparse.Namespace(tid="t002"))
    text = _audit_text(fake_repo)
    assert "finish" in text and "tid=t002" in text and "to=done" in text


def test_edit_writes_audit(fake_repo, monkeypatch):
    monkeypatch.setattr(lifecycle, "task_effective_state", lambda *a, **kw: None)
    args = argparse.Namespace(
        tid="t001", title="renamed", note=None, note_append=None,
        review_level=None, depends_on=None, depends_append=None,
        depends_remove=None, conflicts_with=None, conflicts_append=None,
        conflicts_remove=None,
    )
    lifecycle.cmd_edit(args)
    text = _audit_text(fake_repo)
    assert "edit" in text and "tid=t001" in text


def test_drop_audit_failure_reports_pending_audit(fake_repo, monkeypatch):
    def _boom(*a, **kw):
        raise ctx.TaskDataError("disk full")

    monkeypatch.setattr(lifecycle, "append_audit", _boom)
    with pytest.raises(SystemExit) as exc:
        lifecycle.cmd_drop(argparse.Namespace(tid="t001", reason="obsolete"))
    assert "审计" in str(exc.value) and "待补" in str(exc.value)
    # Archive itself succeeded and stays archived (no silent loss).
    assert (fake_repo / "docs/archive/tasks/t001_alpha/task.md").is_file()
