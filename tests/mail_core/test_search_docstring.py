"""A193: search_messages docstring must match the _MATCH implementation."""

from __future__ import annotations

from mail_core.search.index import search_messages


def test_search_messages_docstring_matches_match_branches():
    doc = search_messages.__doc__ or ""
    # document (FTS) covers body_text; ILIKE/trigram fallbacks cover to_text too
    assert "to_text" in doc
    assert "body_text" in doc
    assert "document" in doc
    # the drifted pre-p059 wording must be gone
    assert "subject + from_text" not in doc
