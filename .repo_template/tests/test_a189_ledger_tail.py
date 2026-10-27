"""A189: `ledger tail -n 0` printed the whole ledger and negative -n
produced a misaligned forward slice (``events[-n:]`` with n<=0).

-n must be a positive integer, enforced both at argparse time and in
cmd_ledger_tail itself.
"""
import argparse
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from repo_task import control
from repo_task.cli import _validate_positive_count

EVENTS = [
    {"ts": f"2026-01-0{i}", "event": "reserve", "tid": "t001"}
    for i in range(1, 6)
]


@pytest.mark.parametrize("n", [0, -1, -20])
def test_a189_cmd_rejects_non_positive_n(monkeypatch, n):
    monkeypatch.setattr(control, "ledger_read", lambda: list(EVENTS))
    with pytest.raises(SystemExit):
        control.cmd_ledger_tail(SimpleNamespace(tid=None, n=n))


@pytest.mark.parametrize("raw", ["0", "-3", "abc"])
def test_a189_argparse_type_rejects_non_positive(raw):
    with pytest.raises(argparse.ArgumentTypeError):
        _validate_positive_count(raw)


def test_a189_positive_n_still_tails(monkeypatch, capsys):
    monkeypatch.setattr(control, "ledger_read", lambda: list(EVENTS))
    control.cmd_ledger_tail(SimpleNamespace(tid=None, n=2))
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 2
    assert "2026-01-05" in out[0]
    assert "2026-01-04" in out[1]


def test_a189_cli_rejects_zero_without_traceback():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "task.py"), "ledger", "tail", "-n", "0"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode != 0
    assert "Traceback" not in result.stderr
