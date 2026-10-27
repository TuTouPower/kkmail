"""A298: normalize_subject must recognise common reply/forward variants.

Counted prefixes (Re[2]:) and fullwidth colons (Re：, common from CJK
mail clients) previously survived normalisation, so replies without
References headers produced a different subject_norm and split into
separate threads.
"""

from __future__ import annotations

from mail_core.threading.rules import normalize_subject


def test_counted_reply_prefix_is_stripped():
    assert normalize_subject("Re[2]: Hello") == "hello"
    assert normalize_subject("Re[12]: Hello") == "hello"


def test_counted_prefix_combines_with_plain_prefixes():
    assert normalize_subject("Re[2]: Re: Hello") == "hello"
    assert normalize_subject("Re: Re[3]: Hello") == "hello"


def test_counted_forward_prefix_is_stripped():
    assert normalize_subject("Fw[3]: Hello") == "hello"


def test_fullwidth_colon_is_normalised():
    assert normalize_subject("Re： Hello") == "hello"
    assert normalize_subject("回复：Hello") == "hello"
    assert normalize_subject("转发：Re： Hello") == "hello"


def test_non_numeric_bracket_prefix_is_not_stripped():
    assert normalize_subject("Re[abc]: Hello") == "re[abc]: hello"


def test_existing_prefix_behaviour_unchanged():
    assert normalize_subject("Re: Fwd: Hello") == "hello"
    assert normalize_subject("AW: Hello") == "hello"
    assert normalize_subject("Hello") == "hello"
