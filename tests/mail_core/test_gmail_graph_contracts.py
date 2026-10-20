"""Contract tests for Gmail History / Graph Delta adapters (mocked transport)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mail_core.providers.base import DeltaChange, DeltaPage, MetadataPage, RemoteMessageMeta, ReconcileAction
from mail_core.providers.gmail import GmailNotConfiguredError, GmailProvider
from mail_core.providers.graph import GraphNotConfiguredError, GraphProvider


def _meta(rid: str) -> RemoteMessageMeta:
    return RemoteMessageMeta(
        remote_id=rid,
        subject="s",
        from_address="a@b.c",
        from_name=None,
        sort_time=datetime.now(timezone.utc),
        is_read=False,
        has_attachments=False,
    )


def test_gmail_requires_history_id_and_uses_transport():
    page = DeltaPage(
        changes=[DeltaChange(kind="upsert", remote_id="m1", meta=_meta("m1"))],
        next_cursor={"historyId": "99"},
        exhausted=True,
    )

    def transport(method, path, params):
        assert method == "GET"
        assert path.endswith("/history")
        assert params["startHistoryId"] == "42"
        return {"page": page}

    p = GmailProvider(credential_ref="x", transport=transport)
    out = p.delta_changes("INBOX", {"historyId": "42"})
    assert out.exhausted and out.changes[0].remote_id == "m1"

    with pytest.raises(ValueError):
        GmailProvider(credential_ref="x", transport=transport).delta_changes("INBOX", {})

    with pytest.raises(GmailNotConfiguredError):
        GmailProvider(credential_ref="x").fetch_metadata_page("INBOX", None)


def test_gmail_list_folders_via_transport():
    def transport(method, path, params):
        return {"labels": [{"id": "INBOX", "name": "INBOX"}, {"id": "Label_1", "name": "Work"}]}

    folders = GmailProvider(credential_ref="x", transport=transport).list_folders()
    assert folders[0].role == "inbox"
    assert folders[1].remote_id == "Label_1"


def test_graph_delta_uses_delta_link_and_next_link():
    page1 = DeltaPage(
        changes=[DeltaChange(kind="delete", remote_id="gone")],
        next_cursor={"next_link": "https://graph/delta?page=2"},
        exhausted=False,
    )
    page2 = DeltaPage(changes=(), next_cursor={"delta_link": "https://graph/delta?token=abc"}, exhausted=True)
    calls = []

    def transport(method, path, params):
        calls.append(path)
        if "page=2" in path:
            return {"page": page2}
        return {"page": page1}

    p = GraphProvider(credential_ref="x", transport=transport)
    first = p.delta_changes("inbox", {})
    assert first.changes[0].kind == "delete"
    second = p.delta_changes("inbox", first.next_cursor)
    assert second.exhausted
    assert second.next_cursor["delta_link"].endswith("token=abc")
    assert len(calls) == 2

    with pytest.raises(GraphNotConfiguredError):
        GraphProvider(credential_ref="x").delta_changes("inbox", {"delta_link": "x"})


def test_graph_list_folders_roles():
    def transport(method, path, params):
        return {
            "value": [
                {"id": "aa", "displayName": "Inbox", "role": "inbox"},
                {"id": "bb", "displayName": "Archive", "role": "archive"},
            ]
        }

    folders = GraphProvider(credential_ref="x", transport=transport).list_folders()
    assert [f.role for f in folders] == ["inbox", "archive"]
