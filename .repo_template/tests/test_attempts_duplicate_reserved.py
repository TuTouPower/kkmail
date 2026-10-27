"""A304: duplicate attempt_reserved for same identity must not silently overwrite."""
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from repo_task import context as ctx
from repo_task.attempts import project_attempts


def _reserved(exec_id="a" * 32, **kw):
    return {"event": "attempt_reserved", "tid": "t001", "attempt": 1,
            "execution_id": exec_id, "executor": "inline", "state": "running", **kw}


def test_duplicate_reserved_same_identity_raises():
    events = [_reserved(), _reserved()]
    with pytest.raises(ctx.TaskDataError, match="重复.*attempt_reserved|duplicate"):
        project_attempts(events)


def test_duplicate_reserved_after_terminal_does_not_overwrite():
    events = [
        _reserved(),
        {"event": "attempt_terminal", "tid": "t001", "attempt": 1,
         "execution_id": "a" * 32, "status": "completed"},
        {"event": "report", "tid": "t001", "attempt": 1,
         "execution_id": "a" * 32, "status": "done"},
        _reserved(),
    ]
    with pytest.raises(ctx.TaskDataError):
        project_attempts(events)


def test_distinct_identities_same_attempt_are_allowed():
    events = [_reserved("a" * 32), _reserved("b" * 32)]
    records = project_attempts(events)
    assert len(records) == 2
