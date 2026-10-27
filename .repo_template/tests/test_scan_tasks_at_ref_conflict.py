"""A337: scan_tasks_at_ref must not silently overwrite when active and
archive contain a directory with the same name."""
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from repo_task import context as ctx
from repo_task import store


def _fm(tid="t001", slug="alpha", status="backlog"):
    return ("---\n"
            f'tid: "{tid}"\nslug: "{slug}"\ntitle: "x"\nstatus: "{status}"\n'
            'branch: ""\nworktree: ""\nreview_level: "full"\ndiff_anchor: ""\n'
            'depends_on: ""\nconflicts_with: ""\nnote: ""\n---\nbody\n')


def test_same_name_in_active_and_archive_raises(monkeypatch):
    paths = [
        "docs/tasks/t001_alpha/task.md",
        "docs/archive/tasks/t001_alpha/task.md",
        "docs/tasks/t001_alpha/spec.md",
        "docs/archive/tasks/t001_alpha/spec.md",
    ]

    class R:
        returncode = 0
        stdout = "\n".join(paths)
        stderr = ""

    monkeypatch.setattr(store, "_git", lambda args, **kw: R())
    texts = {
        "docs/tasks/t001_alpha/task.md": _fm(status="backlog"),
        "docs/archive/tasks/t001_alpha/task.md": _fm(status="done"),
    }
    monkeypatch.setattr(store, "git_text_at_ref", lambda ref, p: texts[p])
    with pytest.raises(ctx.TaskDataError, match="同名|冲突"):
        store.scan_tasks_at_ref("main")


def test_scan_tasks_at_ref_batch_cat_file_reads_multiple_tasks(monkeypatch):
    """A47: scan_tasks_at_ref 批量调用 git_batch_text_at_ref 一次性读取全部 task.md。"""
    paths = [
        "docs/tasks/t001_alpha/task.md",
        "docs/tasks/t002_beta/task.md",
        "docs/archive/tasks/t003_gamma/task.md",
    ]

    class R:
        returncode = 0
        stdout = "\n".join(paths)
        stderr = ""

    monkeypatch.setattr(store, "_git", lambda args, **kw: R())
    batch_called_with = []

    def mock_batch(ref, req_paths):
        batch_called_with.append((ref, list(req_paths)))
        return {
            "docs/tasks/t001_alpha/task.md": _fm(tid="t001", slug="alpha", status="backlog"),
            "docs/tasks/t002_beta/task.md": _fm(tid="t002", slug="beta", status="active"),
            "docs/archive/tasks/t003_gamma/task.md": _fm(tid="t003", slug="gamma", status="done"),
        }

    monkeypatch.setattr(store, "git_batch_text_at_ref", mock_batch)
    tasks = store.scan_tasks_at_ref("refs/heads/feature")

    assert len(batch_called_with) == 1
    assert batch_called_with[0][0] == "refs/heads/feature"
    assert set(batch_called_with[0][1]) == set(paths)
    assert len(tasks) == 3
    tids = {t["tid"] for t in tasks}
    assert tids == {"t001", "t002", "t003"}
