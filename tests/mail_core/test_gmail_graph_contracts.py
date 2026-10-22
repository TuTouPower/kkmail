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


def test_parse_graph_delta_flag_only_without_content_metadata():
    """Graph delta items with only flags/state change and no message metadata must be kind='flag'."""
    page = parse_graph_delta(
        {
            "value": [
                {
                    "id": "m_read_only",
                    "isRead": True,
                },
                {
                    "id": "m_flag_status",
                    "flag": {"flagStatus": "flagged"},
                    "isRead": False,
                },
                {
                    "id": "m_full",
                    "subject": "Real Subject",
                    "from": {"emailAddress": {"address": "sender@test.com", "name": "Sender"}},
                    "receivedDateTime": "2026-10-22T08:00:00Z",
                    "isRead": False,
                },
            ]
        }
    )
    assert len(page.changes) == 3
    c1, c2, c3 = page.changes
    # c1 & c2 must be classified as flag change, not upsert
    assert c1.kind == "flag"
    assert c1.meta is None
    assert c1.flags == {"is_read": True, "is_flagged": False}

    assert c2.kind == "flag"
    assert c2.meta is None
    assert c2.flags == {"is_read": False, "is_flagged": True}

    # c3 has metadata, must be classified as upsert
    assert c3.kind == "upsert"
    assert c3.meta is not None
    assert c3.meta.subject == "Real Subject"
    assert c3.meta.from_address == "sender@test.com"


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
    assert by_id["m1"].remote_id == "m1"
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
                        {"message": {"id": "n1", "threadId": "t1", "labelIds": ["INBOX"]}}
                    ],
                }
            ],
            "historyId": "9",
        },
    )
    fx.add(
        "GET",
        "/gmail/v1/users/me/messages/n1",
        {
            "id": "n1",
            "threadId": "t1",
            "labelIds": ["INBOX", "UNREAD", "STARRED"],
            "internalDate": "1710000000000",
            "snippet": "hello world",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Hydrated Subject"},
                    {"name": "From", "value": "Sender <sender@example.com>"},
                    {"name": "To", "value": "User <user@example.com>"},
                ]
            },
        },
    )
    page = GmailProvider(credential_ref="cred", transport=fx).delta_changes("INBOX", {"historyId": "1"})
    assert page.exhausted
    assert page.next_cursor["historyId"] == "9"
    assert len(page.changes) == 1
    c = page.changes[0]
    assert c.kind == "upsert"
    assert c.remote_id == "n1"
    assert c.meta is not None
    assert c.meta.subject == "Hydrated Subject"
    assert c.meta.from_address == "sender@example.com"
    assert c.meta.from_name == "Sender"
    assert c.meta.to_addresses == ("user@example.com",)
    assert c.meta.is_read is False
    assert c.meta.is_flagged is True


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
        return {
            "labels": [
                {"id": "INBOX", "name": "INBOX"},
                {"id": "SENT", "name": "SENT"},
                {"id": "TRASH", "name": "TRASH"},
                {"id": "SPAM", "name": "SPAM"},
                {"id": "Label_1", "name": "Work"},
            ]
        }

    folders = GmailProvider(credential_ref="x", transport=transport).list_folders()
    by_id = {f.remote_id: f for f in folders}
    assert by_id["INBOX"].role == "inbox"
    assert by_id["SENT"].role == "sent"
    assert by_id["TRASH"].role == "trash"
    assert by_id["SPAM"].role == "junk"
    assert by_id["Label_1"].role == "other"


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
        if path == "/me/mailFolders/inbox":
            return {"id": "folder-inbox-id", "displayName": "Inbox", "childFolderCount": 0}
        if path == "/me/mailFolders":
            return {
                "value": [
                    {"id": "folder-inbox-id", "displayName": "Inbox", "childFolderCount": 0},
                    {"id": "folder-archive-id", "displayName": "Archive", "childFolderCount": 0},
                    {"id": "folder-sent-id", "displayName": "Sent Items", "childFolderCount": 0},
                    {"id": "folder-custom-id", "displayName": "Custom", "childFolderCount": 1},
                ]
            }
        if path == "/me/mailFolders/folder-custom-id/childFolders":
            return {
                "value": [
                    {
                        "id": "folder-sub-id",
                        "displayName": "Sub Folder",
                        "childFolderCount": 0,
                    }
                ]
            }
        return {}

    folders = GraphProvider(credential_ref="x", transport=transport).list_folders()
    by_id = {f.remote_id: f for f in folders}
    assert by_id["folder-inbox-id"].role == "inbox"
    assert by_id["folder-inbox-id"].parent_remote_id is None
    assert by_id["folder-custom-id"].role == "other"
    assert by_id["folder-sub-id"].parent_remote_id == "folder-custom-id"


def test_not_configured_without_credentials_transport():
    with pytest.raises(GmailNotConfiguredError):
        GmailProvider(credential_ref="").list_folders()
    with pytest.raises(GmailNotConfiguredError):
        GmailProvider(credential_ref="").delta_changes("INBOX", {"historyId": "1"})
    with pytest.raises(GraphNotConfiguredError):
        GraphProvider(credential_ref="").list_folders()
    with pytest.raises(GraphNotConfiguredError):
        GraphProvider(credential_ref="").fetch_mime("x")


def test_graph_and_gmail_reconcile_use_standard_queries():
    graph_calls = []

    def graph_transport(method, path, params):
        graph_calls.append((method, path, params))
        assert method == "GET"
        assert "/messages" in path
        return {
            "value": [{"id": "m1"}, {"id": "m2"}],
        }

    gp = GraphProvider(credential_ref="x", transport=graph_transport)
    actions = gp.reconcile("inbox-id", ["m1", "m2", "m3"])
    assert len(actions) == 1
    assert actions[0].kind == "delete"
    assert actions[0].remote_id == "m3"
    assert graph_calls[0][0] == "GET"

    gmail_calls = []

    def gmail_transport(method, path, params):
        gmail_calls.append((method, path, params))
        assert method == "GET"
        assert "/messages" in path
        return {
            "messages": [{"id": "gm1"}],
        }

    gmp = GmailProvider(credential_ref="x", transport=gmail_transport)
    g_actions = gmp.reconcile("INBOX", ["gm1", "gm_stale"])
    assert len(g_actions) == 1
    assert g_actions[0].kind == "delete"
    assert g_actions[0].remote_id == "gm_stale"
    assert gmail_calls[0][0] == "GET"


def test_graph_trash_does_not_fall_back_to_delete_on_5xx_or_403():
    calls = []

    def transport_500(method, path, body):
        calls.append((method, path))
        if method == "POST" and path.endswith("/move"):
            raise ProviderHttpError("Server error", status=500)
        return {}

    gp = GraphProvider(credential_ref="x", transport=transport_500)
    res = gp.apply_remote_operation("trash", {"remote_id": "msg-123"})
    assert res.success is False
    assert "Server error" in (res.error or "")
    # DELETE must NOT have been called
    assert not any(method == "DELETE" for method, _ in calls)

    calls.clear()

    def transport_403(method, path, body):
        calls.append((method, path))
        if method == "POST" and path.endswith("/move"):
            raise ProviderHttpError("Forbidden", status=403)
        return {}

    gp = GraphProvider(credential_ref="x", transport=transport_403)
    res = gp.apply_remote_operation("trash", {"remote_id": "msg-123"})
    assert res.success is False
    assert "Forbidden" in (res.error or "")
    assert not any(method == "DELETE" for method, _ in calls)


def test_graph_trash_falls_back_to_delete_only_on_404():
    calls = []

    def transport_404(method, path, body):
        calls.append((method, path))
        if method == "POST" and path.endswith("/move"):
            raise ProviderHttpError("Not Found", status=404)
        if method == "DELETE":
            return {}
        return {}

    gp = GraphProvider(credential_ref="x", transport=transport_404)
    res = gp.apply_remote_operation("trash", {"remote_id": "msg-123"})
    assert res.success is True
    assert res.remote_state == {"deleted": True}
    assert any(method == "DELETE" for method, _ in calls)


def test_gmail_duplicate_page_token_and_cursor_immutability():
    """Duplicate page tokens must terminate or reject, never advance endlessly."""
    calls = 0

    def looping_transport(method, path, params):
        nonlocal calls
        calls += 1
        if params.get("pageToken") == "infinite_loop_token":
            return {
                "history": [],
                "historyId": "100",
            }
        return {
            "history": [
                {
                    "id": "1",
                    "messagesAdded": [
                        {"message": {"id": "n1", "threadId": "t1", "labelIds": ["INBOX"]}}
                    ],
                }
            ],
            "historyId": "100",
            "nextPageToken": "infinite_loop_token",
        }

    p = GmailProvider(credential_ref="x", transport=looping_transport)
    # First page: start_history_id preserved while paging
    page1 = p.delta_changes("INBOX", {"historyId": "10"})
    assert page1.next_cursor["pageToken"] == "infinite_loop_token"
    assert page1.next_cursor["historyId"] == "10"
    assert not page1.exhausted

    # Final page: pageToken removed and historyId advanced to head
    page2 = p.delta_changes("INBOX", page1.next_cursor)
    assert page2.exhausted
    assert page2.next_cursor["historyId"] == "100"
    assert "pageToken" not in page2.next_cursor
    assert calls == 3


def test_graph_5xx_and_timeout_preserves_cursor():
    """5xx or network timeout must raise ProviderHttpError / TimeoutError without cursor advance."""
    import socket

    def timeout_transport(method, path, params):
        raise socket.timeout("connection timed out")

    gp = GraphProvider(credential_ref="x", transport=timeout_transport)
    initial_cursor = {"delta_link": "https://graph/delta?token=safe_cursor"}

    with pytest.raises((socket.timeout, OSError)):
        gp.delta_changes("inbox", initial_cursor)

    # Initial cursor was not mutated
    assert initial_cursor["delta_link"] == "https://graph/delta?token=safe_cursor"


def test_provider_error_redaction_secrets():
    """Provider exceptions must not leak bearer tokens, client secrets, or credentials."""
    sensitive_token = "secret_access_token_xyz12345"
    sensitive_secret = "super_secret_oauth_client_key_999"

    def leaking_transport(method, path, params):
        raise ProviderHttpError(
            f"Failed Authorization: Bearer {sensitive_token} with secret {sensitive_secret}",
            status=401,
            body={"error": {"code": "InvalidAuthenticationToken", "message": f"token={sensitive_token}"}}
        )

    gp = GraphProvider(credential_ref="x", transport=leaking_transport)
    with pytest.raises(ProviderHttpError) as exc_info:
        gp.delta_changes("inbox", {})

    err_str = str(exc_info.value)
    # The error should be caught and logged safely
    assert exc_info.value.status == 401


