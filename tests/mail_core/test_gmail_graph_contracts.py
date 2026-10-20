"""Contract tests for Gmail History / Graph Delta (injectable transport + fixtures)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mail_core.providers.base import DeltaChange, DeltaPage, RemoteMessageMeta
from mail_core.providers.gmail import GmailNotConfiguredError, GmailProvider
from mail_core.providers.graph import GraphNotConfiguredError, GraphProvider
from mail_core.providers.http import CursorInvalidError, FixtureTransport, ProviderHttpError, RateLimitedError
from mail_core.providers.parsing.gmail_history import parse_gmail_history
from mail_core.providers.parsing.graph_delta import parse_graph_delta


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


# --- raw parsers -----------------------------------------------------------

def test_parse_graph_delta_pagination_and_removed():
    page1 = parse_graph_delta(
        {
            "@odata.nextLink": "https://graph.microsoft.com/v1.0/delta?skiptoken=2",
            "value": [
                {
                    "id": "m1",
                    "subject": "Hello",
                    "from": {"emailAddress": {"address": "a@b.c", "name": "A"}},
                    "receivedDateTime": "2024-06-01T12:00:00Z",
                    "isRead": False,
                    "hasAttachments": True,
                    "bodyPreview": "hi",
                    "conversationId": "c1",
                },
                {"id": "gone", "@removed": {"reason": "deleted"}},
            ],
        }
    )
    assert not page1.exhausted
    assert page1.next_cursor["next_link"].endswith("skiptoken=2")
    kinds = {c.remote_id: c.kind for c in page1.changes}
    assert kinds == {"m1": "upsert", "gone": "delete"}
    assert page1.changes[0].meta.subject == "Hello"

    page2 = parse_graph_delta(
        {
            "@odata.deltaLink": "https://graph.microsoft.com/v1.0/delta?deltatoken=abc",
            "value": [],
        }
    )
    assert page2.exhausted
    assert page2.next_cursor["delta_link"].endswith("deltatoken=abc")


def test_parse_gmail_history_pagination_add_delete_flag():
    page = parse_gmail_history(
        {
            "history": [
                {
                    "id": "100",
                    "messagesAdded": [
                        {
                            "message": {
                                "id": "m1",
                                "threadId": "t1",
                                "labelIds": ["INBOX", "UNREAD"],
                                "snippet": "yo",
                                "payload": {
                                    "headers": [
                                        {"name": "Subject", "value": "Subj"},
                                        {"name": "From", "value": "Ann <ann@ex.com>"},
                                    ]
                                },
                            }
                        }
                    ],
                    "messagesDeleted": [{"message": {"id": "old"}}],
                    "labelsRemoved": [
                        {"message": {"id": "m2", "labelIds": ["INBOX"]}, "labelIds": ["UNREAD"]}
                    ],
                }
            ],
            "historyId": "150",
            "nextPageToken": "page2",
        },
        folder_label="INBOX",
    )
    assert not page.exhausted
    assert page.next_cursor == {"historyId": "150", "pageToken": "page2"}
    by_id = {c.remote_id: c for c in page.changes}
    assert by_id["old"].kind == "delete"
    assert by_id["m1"].kind == "upsert"
    assert by_id["m1"].meta.subject == "Subj"
    assert by_id["m2"].kind == "flag"
    assert by_id["m2"].flags.get("is_read") is True


# --- provider + transport --------------------------------------------------

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


def test_gmail_raw_history_via_fixture_transport():
    fx = FixtureTransport()
    fx.add(
        "GET",
        "/gmail/v1/users/me/history",
        {
            "history": [
                {
                    "id": "1",
                    "messagesAdded": [
                        {"message": {"id": "n1", "labelIds": ["INBOX"], "snippet": "x", "subject": "N"}}
                    ],
                }
            ],
            "historyId": "9",
        },
    )
    page = GmailProvider(credential_ref="cred", transport=fx).delta_changes("INBOX", {"historyId": "1"})
    assert page.exhausted
    assert page.changes[0].remote_id == "n1"
    assert page.next_cursor["historyId"] == "9"


def test_gmail_429_and_invalid_history():
    def boom_429(method, path, params):
        raise RateLimitedError("quota", retry_after_seconds=12, headers={"Retry-After": "12"})

    with pytest.raises(RateLimitedError) as ri:
        GmailProvider(credential_ref="x", transport=boom_429).delta_changes("INBOX", {"historyId": "1"})
    assert ri.value.retry_after_seconds == 12

    def boom_404(method, path, params):
        raise ProviderHttpError("historyId not found", status=404, body={"error": {"message": "historyId invalid"}})

    with pytest.raises(CursorInvalidError):
        GmailProvider(credential_ref="x", transport=boom_404).delta_changes("INBOX", {"historyId": "stale"})


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


def test_graph_raw_delta_pagination_fixture():
    fx = FixtureTransport()

    def router(method, path, params):
        if "skiptoken=2" in path:
            return {"@odata.deltaLink": "https://graph/delta?deltatoken=z", "value": []}
        return {
            "@odata.nextLink": "https://graph/delta?skiptoken=2",
            "value": [
                {
                    "id": "aa",
                    "subject": "S",
                    "from": {"emailAddress": {"address": "u@x.com"}},
                    "receivedDateTime": "2024-01-01T00:00:00Z",
                    "isRead": True,
                    "hasAttachments": False,
                }
            ],
        }

    fx.add("GET", "/me/mailFolders/inbox/messages/delta", router)
    fx.add("GET", "https://graph/delta?skiptoken=2", router)
    p = GraphProvider(credential_ref="x", transport=fx)
    first = p.delta_changes("inbox", {})
    assert not first.exhausted and first.changes[0].meta.subject == "S"
    second = p.delta_changes("inbox", first.next_cursor)
    assert second.exhausted and second.next_cursor["delta_link"].endswith("deltatoken=z")


def test_graph_429_and_sync_state_not_found():
    def boom_429(method, path, params):
        raise ProviderHttpError("throttled", status=429, headers={"Retry-After": "30"})

    with pytest.raises(RateLimitedError):
        GraphProvider(credential_ref="x", transport=boom_429).delta_changes("inbox", {})

    def boom_410(method, path, params):
        raise ProviderHttpError("gone", status=410, body={"error": {"code": "syncStateNotFound"}})

    with pytest.raises(CursorInvalidError):
        GraphProvider(credential_ref="x", transport=boom_410).delta_changes(
            "inbox", {"delta_link": "https://graph/delta?deltatoken=stale"}
        )


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


def test_not_configured_without_credentials_transport():
    with pytest.raises(GmailNotConfiguredError):
        GmailProvider(credential_ref="").list_folders()
    with pytest.raises(GmailNotConfiguredError):
        GmailProvider(credential_ref="").delta_changes("INBOX", {"historyId": "1"})
    with pytest.raises(GraphNotConfiguredError):
        GraphProvider(credential_ref="").list_folders()
    with pytest.raises(GraphNotConfiguredError):
        GraphProvider(credential_ref="").fetch_mime("x")
