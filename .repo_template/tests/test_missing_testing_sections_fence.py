"""A262: _missing_testing_sections fence closing must match documents:
same char AND closing length >= opening length."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from repo_task.lifecycle import _missing_testing_sections


def test_shorter_closing_fence_does_not_close():
    text = (
        "## doctor_cmd\n\n"
        "````bash\n"
        "```\n"
        "## test_cmd\n\n"
        "pytest -q\n\n"
        "````\n"
    )
    # The ``` line and the ## test_cmd heading are inside the 4-backtick
    # fence, so test_cmd is never a real section; doctor counts via fence.
    assert _missing_testing_sections(text) == ["{test_cmd}", "{blackbox_verify}"]


def test_longer_closing_fence_closes():
    text = (
        "## doctor_cmd\n\n"
        "```bash\npytest --collect-only\n````\n\n"
        "## test_cmd\n\npytest -q\n\n"
        "## blackbox_verify\n\n无\n"
    )
    assert _missing_testing_sections(text) == []
