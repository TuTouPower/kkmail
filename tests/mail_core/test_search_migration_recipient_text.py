"""A118: runtime _format_recipient_text form and unified baseline recipient search text."""

from __future__ import annotations

from pathlib import Path

from mail_core.search.index import _format_recipient_text

_VERSIONS = Path(__file__).resolve().parents[2] / "src" / "mail_core" / "db" / "alembic" / "versions"
_BASELINE = _VERSIONS / "20261107_0001_unified_baseline.py"


def test_runtime_recipient_form_is_name_plus_address():
    assert _format_recipient_text([{"name": "Ann", "address": "ann@example.com"}]) == "Ann ann@example.com"
    assert _format_recipient_text(["plain@example.com"]) == "plain@example.com"


def test_baseline_includes_recipient_search_text_and_addresses():
    assert _BASELINE.exists(), "unified baseline missing"
    src = _BASELINE.read_text(encoding="utf-8")
    assert "to_text" in src
    assert "recipient_addresses" in src
