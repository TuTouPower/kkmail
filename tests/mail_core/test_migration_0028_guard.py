"""A118-SUP: the 0028 rebuild must skip non-array address JSON per row.

0027 (A25) guards both of its backfills with
``jsonb_typeof(<col>) = 'array'`` so historical rows whose address JSON
is a scalar/object/NULL are skipped instead of aborting the upgrade.
0028 expands ``m.to_addresses`` / ``m.cc_addresses`` with
``jsonb_array_elements`` in three places but originally had no such
guard: a non-array row that 0027 skipped would still crash the rebuild
when a database upgrades through the full chain to 0028.

PG is unavailable locally, so — like the A25/A118 migration tests —
these tests pin the migration source and require every expansion call
site to carry the same guard shape as 0027.
"""

from __future__ import annotations

import re
from pathlib import Path

_VERSIONS = (
    Path(__file__).resolve().parents[2]
    / "src/mail_core/db/alembic/versions"
)
_MIG_0027 = _VERSIONS / "20261027_0027_search_recipient_and_account_recipients.py"
_MIG_0028 = _VERSIONS / "20261027_0028_rebuild_recipient_search_text.py"

_EXPANSION = re.compile(r"jsonb_array_elements\(m\.(\w+)\)")
_GUARD = re.compile(r"jsonb_typeof\(m\.(\w+)\) = 'array'")


def _expansions(src: str) -> list[str]:
    return _EXPANSION.findall(src)


def _guards(src: str) -> list[str]:
    return _GUARD.findall(src)


def test_0028_expands_addresses_in_three_places():
    src = _MIG_0028.read_text(encoding="utf-8")
    # accounts rebuild (to) + message_search rebuild (to UNION ALL cc).
    assert _expansions(src) == ["to_addresses", "to_addresses", "cc_addresses"]


def test_every_0028_expansion_has_a_matching_array_guard():
    src = _MIG_0028.read_text(encoding="utf-8")
    # One guard per expansion, on the same column being expanded.
    assert sorted(_guards(src)) == sorted(_expansions(src))


def test_each_0028_expansion_segment_carries_its_own_guard():
    src = _MIG_0028.read_text(encoding="utf-8")
    # Split at each expansion call; the text up to the next expansion
    # (its own subquery's WHERE clause) must contain that column's guard,
    # so a guard cannot "cover" a different call site by accident.
    parts = _EXPANSION.split(src)
    # parts: [prefix, col1, segment1, col2, segment2, col3, segment3]
    assert len(parts) == 1 + 2 * 3
    for i in range(3):
        column = parts[1 + 2 * i]
        segment = parts[2 + 2 * i]
        assert f"jsonb_typeof(m.{column}) = 'array'" in segment


def test_0028_guard_shape_matches_0027():
    src27 = _MIG_0027.read_text(encoding="utf-8")
    src28 = _MIG_0028.read_text(encoding="utf-8")
    # 0027's A25 guard predicate form, verbatim, is what 0028 must use.
    guard_form = "jsonb_typeof(m.to_addresses) = 'array'"
    assert guard_form in src27
    assert guard_form in src28
    # And the guarded columns in 0028 are exactly the expanded columns.
    assert set(_guards(src28)) == {"to_addresses", "cc_addresses"}
