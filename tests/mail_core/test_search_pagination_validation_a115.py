"""A115: both application-layer search entries must validate pagination.

search_message_ids used to forward any limit/offset to the search layer
(negative offsets were silently clamped deep below, oversized offsets
bypassed MAX_SEARCH_OFFSET entirely), and search_messages_page relied on
the API route's Query constraints alone. Validation now lives at the
application boundary shared by both entries.
"""

from __future__ import annotations

import pytest

import mail_core.mail.application.search as search_app


class _Session:
    pass


@pytest.fixture
def captured(monkeypatch):
    calls: dict = {}

    def fake_ids(session, **kwargs):
        calls["ids"] = kwargs
        return []

    def fake_page(session, **kwargs):
        calls["page"] = kwargs
        return [], 0

    monkeypatch.setattr(search_app, "_search_messages", fake_ids)
    monkeypatch.setattr(search_app, "_search_messages_with_total", fake_page)
    monkeypatch.setattr(search_app, "messages_by_ids", lambda session, ids: [])
    return calls


@pytest.mark.parametrize("limit", [0, -1, 201, 10_000])
def test_search_message_ids_rejects_out_of_range_limit(captured, limit):
    with pytest.raises(ValueError, match="limit"):
        search_app.search_message_ids(_Session(), query="x", limit=limit)


@pytest.mark.parametrize("offset", [-1, search_app.MAX_SEARCH_OFFSET + 1])
def test_search_message_ids_rejects_out_of_range_offset(captured, offset):
    with pytest.raises(ValueError, match="offset"):
        search_app.search_message_ids(_Session(), query="x", offset=offset)


@pytest.mark.parametrize("limit", [0, 201])
def test_search_messages_page_rejects_out_of_range_limit(captured, limit):
    with pytest.raises(ValueError, match="limit"):
        search_app.search_messages_page(_Session(), query="x", limit=limit)


@pytest.mark.parametrize("offset", [-5, search_app.MAX_SEARCH_OFFSET + 1])
def test_search_messages_page_rejects_out_of_range_offset(captured, offset):
    with pytest.raises(ValueError, match="offset"):
        search_app.search_messages_page(_Session(), query="x", offset=offset)


def test_boundary_values_are_accepted(captured):
    assert search_app.search_message_ids(_Session(), query="x", limit=1, offset=0) == []
    assert (
        search_app.search_message_ids(
            _Session(), query="x", limit=200, offset=search_app.MAX_SEARCH_OFFSET
        )
        == []
    )
    page = search_app.search_messages_page(_Session(), query="x", limit=200, offset=0)
    assert page.total == 0
    # The page entry may look one row ahead internally (limit + 1) without
    # tripping its own validation.
    assert captured["page"]["limit"] == 201
