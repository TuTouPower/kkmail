"""A168: core status/count columns need DB-level CHECK constraints.

Illegal values previously entered the DB freely and only exploded later
in the application layer as ValueError. Minimum coverage per the fix
note: archive state enum, message_blobs.ref_count >= 0 and
blob_quota_reservations.reserved_bytes > 0 — in the ORM models and in a
migration with matching constraint names.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import CheckConstraint

from mail_core.db.base import Base
from mail_core.mail.domain.enums import ArchiveState

import mail_core.mail.storage.models  # noqa: F401  (register tables)

VERSIONS = Path(__file__).resolve().parents[2] / "src" / "mail_core" / "db" / "alembic" / "versions"
MIGRATION = VERSIONS / "20261027_0029_check_constraints_core.py"

EXPECTED = {
    "message_archive_state": "ck_message_archive_state_state_valid",
    "message_blobs": "ck_message_blobs_ref_count_nonnegative",
    "blob_quota_reservations": "ck_blob_quota_reservations_reserved_bytes_positive",
}


def _check(table_name: str) -> CheckConstraint:
    table = Base.metadata.tables[table_name]
    for constraint in table.constraints:
        if isinstance(constraint, CheckConstraint) and constraint.name == EXPECTED[table_name]:
            return constraint
    raise AssertionError(f"{table_name} missing CHECK {EXPECTED[table_name]}")


def test_archive_state_check_covers_every_enum_value():
    sql = str(_check("message_archive_state").sqltext)
    for state in ArchiveState:
        assert state.value in sql


def test_ref_count_check_is_nonnegative():
    sql = str(_check("message_blobs").sqltext)
    assert "ref_count" in sql and ">= 0" in sql


def test_reserved_bytes_check_is_positive():
    sql = str(_check("blob_quota_reservations").sqltext)
    assert "reserved_bytes" in sql and "> 0" in sql


def test_migration_adds_same_named_constraints_on_0028():
    assert MIGRATION.is_file(), "migration 0029 missing"
    text = MIGRATION.read_text(encoding="utf-8")
    assert 'revision: str = "20261027_0029"' in text
    assert 'down_revision: Union[str, None] = "20261027_0028"' in text
    for name in EXPECTED.values():
        assert name in text
    assert "create_check_constraint" in text
    assert "drop_check_constraint" in text
