"""A25: the 0027 backfill must survive non-array to_addresses and big tables.

The original backfill ran ``jsonb_array_elements(m.to_addresses)`` in a
correlated subquery for every account / message_search row with no
shape guard: one historical row whose ``to_addresses`` is a JSON scalar
or object aborts the whole upgrade. It also ran as two whole-table
statements with no batching. PG is unavailable locally, so — like the
existing A118 migration tests — these tests pin the migration source,
plus the pure-Python batching helper's behaviour.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_MIG = (
    Path(__file__).resolve().parents[2]
    / "src/mail_core/db/alembic/versions/20261027_0027_search_recipient_and_account_recipients.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_0027_a25", _MIG)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_backfills_guard_to_addresses_shape():
    src = _MIG.read_text(encoding="utf-8")
    # One guard per backfill (accounts + message_search).
    assert src.count("jsonb_typeof(m.to_addresses) = 'array'") == 2


def test_backfill_is_batched_by_id_and_notes_large_table_cost():
    src = _MIG.read_text(encoding="utf-8")
    assert "_BACKFILL_BATCH_SIZE" in src
    assert "expanding=True" in src
    # The migration itself must warn operators about large-table cost.
    assert "large" in src.lower()


def test_chunks_helper_splits_in_order():
    migration = _load_migration()
    chunks = list(migration._chunks([1, 2, 3, 4, 5], 2))
    assert chunks == [[1, 2], [3, 4], [5]]
    assert list(migration._chunks([], 2)) == []
