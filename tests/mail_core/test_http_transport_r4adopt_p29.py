"""A376: ``FixtureTransport`` prefix routes must resolve by LONGEST
matching prefix, not by route insertion order.
"""

from __future__ import annotations

import pytest

from mail_core.providers.http import FixtureTransport, ProviderHttpError


def test_fixture_transport_prefers_longest_prefix_over_insertion_order():
    transport = FixtureTransport()
    transport.add("GET", "/me", {"route": "short"})
    transport.add("GET", "/me/mailFolders", {"route": "long"})

    assert transport("GET", "/me/mailFolders/inbox/messages") == {"route": "long"}
    assert transport("GET", "/me/messages") == {"route": "short"}


def test_fixture_transport_longest_prefix_regardless_of_reverse_insertion():
    transport = FixtureTransport()
    transport.add("GET", "/me/mailFolders", {"route": "long"})
    transport.add("GET", "/me", {"route": "short"})

    assert transport("GET", "/me/mailFolders/inbox") == {"route": "long"}


def test_fixture_transport_exact_match_and_404_unchanged():
    transport = FixtureTransport()
    transport.add("GET", "/me/mailFolders", {"route": "exact"})

    assert transport("GET", "/me/mailFolders") == {"route": "exact"}
    with pytest.raises(ProviderHttpError):
        transport("GET", "/nope")
