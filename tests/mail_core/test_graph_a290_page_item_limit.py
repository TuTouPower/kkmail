"""A290: fetch_metadata_page / delta_changes must cap single-page items.

list_folders and reconcile already enforce MAX_GRAPH_ITEMS_PER_CALL;
a single metadata/delta page larger than that must be rejected with
GraphPaginationError before parsing, not materialized unbounded.
"""

from __future__ import annotations

import pytest

from mail_core.providers.graph import (
    MAX_GRAPH_ITEMS_PER_CALL,
    GraphPaginationError,
    GraphProvider,
)


def _provider_with_page(size: int) -> GraphProvider:
    page = {"value": [{"id": f"m{i}"} for i in range(size)]}

    def transport(method, path, params):
        return page

    return GraphProvider(credential_ref="x", transport=transport)


def test_a290_fetch_metadata_page_rejects_oversized_page():
    provider = _provider_with_page(MAX_GRAPH_ITEMS_PER_CALL + 1)
    with pytest.raises(GraphPaginationError):
        provider.fetch_metadata_page("folder-1", None)


def test_a290_delta_changes_rejects_oversized_page():
    provider = _provider_with_page(MAX_GRAPH_ITEMS_PER_CALL + 1)
    with pytest.raises(GraphPaginationError):
        provider.delta_changes("folder-1", {})


def test_a290_page_at_limit_is_accepted():
    provider = _provider_with_page(MAX_GRAPH_ITEMS_PER_CALL)
    page = provider.fetch_metadata_page("folder-1", None)
    assert len(page.items) == MAX_GRAPH_ITEMS_PER_CALL
