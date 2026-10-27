"""A118: migration backfill must match runtime _format_recipient_text form.

Runtime turns a dict recipient into "name address" plain text and a string
recipient into itself. The 0027 backfill used jsonb_array_elements_text,
which expands dict elements into whole JSON text; a rebuild migration for
already-migrated databases must use the same corrected extraction.
PG is unavailable locally, so these tests pin the migration SQL source
(the SQL itself only runs on PostgreSQL).
"""

from __future__ import annotations

from pathlib import Path

from mail_core.search.index import _format_recipient_text

_VERSIONS = Path(__file__).resolve().parents[2] / "src" / "mail_core" / "db" / "alembic" / "versions"
_MIG_0027 = _VERSIONS / "20261027_0027_search_recipient_and_account_recipients.py"
_MIG_0028 = _VERSIONS / "20261027_0028_rebuild_recipient_search_text.py"


def test_runtime_recipient_form_is_name_plus_address():
    assert _format_recipient_text([{"name": "Ann", "address": "ann@example.com"}]) == "Ann ann@example.com"
    assert _format_recipient_text(["plain@example.com"]) == "plain@example.com"


def test_0027_backfill_does_not_expand_dict_recipients_to_json_text():
    src = _MIG_0027.read_text(encoding="utf-8")
    assert "jsonb_array_elements_text" not in src
    assert "jsonb_array_elements(" in src
    assert "->>'address'" in src
    assert "->>'name'" in src


def test_0028_rebuild_migration_exists_and_corrects_both_tables():
    assert _MIG_0028.exists(), "already-migrated DBs need a rebuild migration"
    src = _MIG_0028.read_text(encoding="utf-8")
    assert 'revision: str = "20261027_0028"' in src
    assert 'down_revision: Union[str, None] = "20261027_0027"' in src
    assert "jsonb_array_elements_text" not in src
    assert "->>'address'" in src
    assert "->>'name'" in src
    # to_text rebuild covers cc as well (runtime includes cc after A58)
    assert "cc_addresses" in src
    # both polluted columns are rebuilt
    assert "message_search" in src
    assert "recipient_addresses" in src
