"""A206: ledger reads re-parsed the whole JSONL file on every call, and a
single command may call ledger_read() repeatedly.

Within one process, ledger_read() must reuse the snapshot taken under
the lock while the file is unchanged (size+mtime), and must observe
writes made through ledger_append(). The module must also document an
archiving strategy for the append-only ledger.
"""
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import repo_task.context as ctx
from repo_task import ledger


@pytest.fixture
def ledger_file(tmp_path, monkeypatch):
    path = tmp_path / "dispatch_ledger.jsonl"
    path.write_text(
        "".join(
            json.dumps({"event": "reserve", "tid": "t001", "seq": i}) + "\n"
            for i in range(3)
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ctx, "LEDGER_PATH", path)
    if hasattr(ledger, "_read_cache"):
        monkeypatch.setattr(ledger, "_read_cache", None)
    return path


def _counting_read(monkeypatch):
    calls = {"n": 0}
    original = ledger._read_unlocked

    def counting():
        calls["n"] += 1
        return original()

    monkeypatch.setattr(ledger, "_read_unlocked", counting)
    return calls


def test_a206_repeated_reads_reuse_single_parse(ledger_file, monkeypatch):
    calls = _counting_read(monkeypatch)
    first = ledger.ledger_read()
    second = ledger.ledger_read()
    assert first == second
    assert calls["n"] == 1, "unchanged ledger must be parsed once per process"


def test_a206_read_after_append_observes_new_event(ledger_file, monkeypatch):
    calls = _counting_read(monkeypatch)
    assert len(ledger.ledger_read()) == 3
    ledger.ledger_append({"event": "report", "tid": "t001"})
    events = ledger.ledger_read()
    assert len(events) == 4
    assert events[-1]["event"] == "report"
    assert calls["n"] >= 2, "a write must invalidate/replace the cached snapshot"


def test_a206_returned_events_are_copies(ledger_file):
    first = ledger.ledger_read()
    first[0]["event"] = "corrupted"
    assert ledger.ledger_read()[0]["event"] == "reserve"


def test_a206_archiving_strategy_documented():
    doc = (ledger.__doc__ or "") + (ledger.ledger_read.__doc__ or "")
    assert "归档" in doc or "archive" in doc.lower()
    assert hasattr(ledger, "LEDGER_ARCHIVE_THRESHOLD_EVENTS")
