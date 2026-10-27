"""A306: .env.test subset parser — paired quotes only, export prefix,
inline comments for unquoted values; quote chars that are part of the
value must survive (the old strip("'\\"") mangled them).
"""

import importlib.util
import os
from pathlib import Path

import pytest


def _load_runner():
    root = Path(__file__).resolve().parents[2]
    path = root / "scripts/run_full_stack_e2e.py"
    spec = importlib.util.spec_from_file_location("run_full_stack_e2e_env_parse", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


KEYS = [
    "T_PLAIN", "T_EXPORT", "T_DQUOTED", "T_SQUOTED", "T_COMMENTED",
    "T_TRAILING_QUOTE", "T_MISMATCHED", "T_LONE_QUOTE", "T_EMPTY_QUOTED",
    "T_PRESET",
]


@pytest.fixture
def parsed(tmp_path, monkeypatch):
    module = _load_runner()
    module.ROOT = tmp_path
    for key in KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("T_PRESET", "preset-value")
    (tmp_path / ".env.test").write_text(
        "\n".join([
            "# a comment line",
            "",
            "T_PLAIN=plain",
            "export T_EXPORT=exported",
            'T_DQUOTED="va # lue"',
            "T_SQUOTED='single quoted'",
            "T_COMMENTED=value # trailing comment",
            'T_TRAILING_QUOTE=abc"',
            "T_MISMATCHED=\"abc'",
            'T_LONE_QUOTE="',
            'T_EMPTY_QUOTED=""',
            "T_PRESET=from-file",
            "LINE_WITHOUT_EQUALS",
        ]) + "\n",
        encoding="utf-8",
    )
    module.load_env_test()
    return os.environ


def test_plain_and_export_prefix(parsed):
    assert parsed["T_PLAIN"] == "plain"
    assert parsed["T_EXPORT"] == "exported"


def test_paired_quotes_stripped_as_pair_only(parsed):
    assert parsed["T_DQUOTED"] == "va # lue"  # # inside quotes survives
    assert parsed["T_SQUOTED"] == "single quoted"
    assert parsed["T_EMPTY_QUOTED"] == ""


def test_unquoted_inline_comment_stripped(parsed):
    assert parsed["T_COMMENTED"] == "value"


def test_quote_chars_belonging_to_value_survive(parsed):
    # Old parser strip("'\"") would have turned these into abc / abc / ''.
    assert parsed["T_TRAILING_QUOTE"] == 'abc"'
    assert parsed["T_MISMATCHED"] == "\"abc'"
    assert parsed["T_LONE_QUOTE"] == '"'


def test_existing_environment_wins(parsed):
    assert parsed["T_PRESET"] == "preset-value"
