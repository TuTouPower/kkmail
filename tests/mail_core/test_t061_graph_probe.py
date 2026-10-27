"""t061 AC-008/AC-010 adapter layer: GraphProvider.probe_folder_status.

The patrol's scheduling logic is covered with injected fake providers;
this file pins the real Graph adapter's field mapping (spec spike:
Graph mailFolder GET returns totalItemCount / unreadItemCount, which
are the probe's change dimensions; no UIDNEXT/modseq equivalents).
"""

from __future__ import annotations

from mail_core.providers.base import FolderStatus
from mail_core.providers.graph import GraphProvider


def _provider(payload):
    def transport(method, path, params):
        assert method == "GET"
        assert path == "/me/mailFolders/folder-1"
        return payload

    return GraphProvider(credential_ref="x", transport=transport)


def test_graph_probe_maps_counts():
    provider = _provider({"totalItemCount": 42, "unreadItemCount": 7})
    assert provider.probe_folder_status("folder-1") == FolderStatus(
        messages=42, uidnext=None, unseen=7, highestmodseq=None
    )


def test_graph_probe_missing_counts_are_none_not_zero():
    provider = _provider({"id": "folder-1"})
    status = provider.probe_folder_status("folder-1")
    assert status is not None
    assert status.messages is None and status.unseen is None


def test_graph_probe_non_dict_response_returns_none():
    provider = _provider(["not", "a", "dict"])
    assert provider.probe_folder_status("folder-1") is None
