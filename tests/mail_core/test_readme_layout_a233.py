"""A233: src/mail_core/README.md Layout drifted from the implementation —
the api/ row omitted oauth_routes (which exists in mail_core/api/) and did
not note app.py as the assembly entry point.
"""

from __future__ import annotations

from pathlib import Path

README = Path(__file__).resolve().parents[2] / "src" / "mail_core" / "README.md"


def _api_row() -> str:
    for line in README.read_text(encoding="utf-8").splitlines():
        if line.startswith("|`api/`|"):
            return line
    raise AssertionError("api/ layout row not found in README")


def test_readme_api_row_lists_oauth_routes():
    assert "oauth_routes" in _api_row()


def test_readme_api_row_notes_app_py_assembly_entry():
    row = _api_row()
    assert "app.py" in row
    assert "assembly" in row.lower()
