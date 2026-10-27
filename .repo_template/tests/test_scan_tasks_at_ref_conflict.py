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
