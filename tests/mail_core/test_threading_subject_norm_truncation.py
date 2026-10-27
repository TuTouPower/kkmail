"""A12: normalize_subject must fit Thread.subject_norm String(998).

Message.subject is Text (unbounded); without truncation a >998-char
subject made assign_thread fail at flush with a DataError and rolled
back the whole metadata page. Both Thread creation sites in
threading/rules.py go through normalize_subject, so the bound lives
there.
"""

from __future__ import annotations

from mail_core.threading.rules import normalize_subject


def test_normalize_subject_truncates_overlong_subject_to_998():
    result = normalize_subject("x" * 1500)
    assert len(result) == 998
    assert result == "x" * 998


def test_normalize_subject_truncates_after_prefix_stripping():
    result = normalize_subject("Re: Fwd: " + "y" * 1500)
    assert len(result) == 998
    assert result == "y" * 998


def test_normalize_subject_exactly_998_is_unchanged():
    subject = "z" * 998
    assert normalize_subject(subject) == subject


def test_normalize_subject_short_subject_unchanged():
    assert normalize_subject("Re: Hello World") == "hello world"
    assert normalize_subject("") == ""
