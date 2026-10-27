"""A236: extract_message_ids mixed angle/bare handling + docstring truth.

Previously any part containing "<" skipped bare extraction entirely, so
a References header mixing one angle-bracket id with bare ids lost the
bare ones. Bare extraction must decide per token: skip only ids already
covered by an angle form in the same part. Duplicates keep the first
occurrence (the old docstring wrongly claimed later headers override).
"""

from __future__ import annotations

from mail_core.threading.rules import extract_message_ids


def test_mixed_angle_and_bare_in_one_part_keeps_both():
    assert extract_message_ids("<a@b.c> bare@d.e") == ["<a@b.c>", "<bare@d.e>"]


def test_unrelated_angle_brackets_do_not_suppress_bare_ids():
    assert extract_message_ids("see <notes> and x@y.z") == ["<x@y.z>"]


def test_bare_duplicate_of_angle_form_is_not_repeated():
    assert extract_message_ids("<a@b.c> a@b.c") == ["<a@b.c>"]


def test_first_occurrence_wins_across_parts():
    assert extract_message_ids("<a@b.c>", "<a@b.c> <b@c.d>") == ["<a@b.c>", "<b@c.d>"]
    assert extract_message_ids("a@b.c", "<a@b.c>") == ["<a@b.c>"]


def test_angle_only_and_bare_only_parts_unchanged():
    assert extract_message_ids("<a@b.c> <c@d.e>", "Re: x") == ["<a@b.c>", "<c@d.e>"]
    assert extract_message_ids("only@bare.id") == ["<only@bare.id>"]
    assert extract_message_ids(None, "") == []
