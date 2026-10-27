"""A222: `view --port` must validate 0..65535 at argparse time.

Previously type=int accepted any integer and an out-of-range port died
later inside serve() with an uncaught OverflowError traceback.
"""
import argparse
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from repo_task.cli import _validate_port


@pytest.mark.parametrize("raw,expected", [("0", 0), ("8080", 8080), ("65535", 65535)])
def test_a222_valid_ports_accepted(raw, expected):
    assert _validate_port(raw) == expected


@pytest.mark.parametrize("raw", ["65536", "70000", "-1", "abc"])
def test_a222_out_of_range_ports_rejected(raw):
    with pytest.raises(argparse.ArgumentTypeError):
        _validate_port(raw)


def test_a222_cli_rejects_out_of_range_port_without_traceback():
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "task.py"), "view", "--serve", "--port", "70000"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 2
    assert "OverflowError" not in result.stderr
    assert "Traceback" not in result.stderr
