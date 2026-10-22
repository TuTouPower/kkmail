"""An isolation reset failure must end pytest before another test executes."""

import os
from pathlib import Path
import subprocess
import sys


def test_setup_cleanup_failure_stops_suite(tmp_path):
    probe = tmp_path / "test_reset_probe.py"
    marker = tmp_path / "unexpected_execution"
    probe.write_text(f"""
import pytest
from pathlib import Path
from tests.mail_core.runtime_isolation import isolated_runtime
import tests.mail_core.runtime_isolation as isolation

@pytest.fixture(autouse=True)
def broken_setup(monkeypatch, tmp_path, request):
    def fail():
        raise RuntimeError('intentional cleanup failure')
    monkeypatch.setattr(isolation, 'clear_database', fail)
    with isolated_runtime(monkeypatch, tmp_path, request.session):
        yield

def test_first():
    Path({str(marker)!r}).touch()

def test_second():
    Path({str(marker)!r}).touch()
""")
    env = os.environ.copy()
    env.pop("MAIL_CORE_DATABASE_URL", None)
    env.pop("MAIL_CORE_REQUIRE_DB", None)
    env.pop("KKMAIL_TEST_REPORT_DIR", None)
    result = subprocess.run([sys.executable, "-m", "pytest", str(probe), "-q"],
                            cwd=Path(__file__).resolve().parents[2], env=env, capture_output=True, text=True)
    assert result.returncode == 2, result.stdout + result.stderr
    assert "backend isolation setup cleanup failed (RuntimeError)" in result.stdout + result.stderr
    assert not marker.exists()
