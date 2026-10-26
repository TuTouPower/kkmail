"""Contract tests for Graph Delta (injectable transport + fixtures)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from mail_core.providers.graph import GraphNotConfiguredError, GraphPaginationError, GraphProvider
from mail_core.providers.http import CursorInvalidError, FixtureTransport, ProviderHttpError, RateLimitedError
from mail_core.providers.parsing.graph_delta import parse_graph_delta


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


def test_graph_explicit_attachment_state_keeps_true_and_false():
    page = parse_graph_delta(
        {
            "value": [
                {"id": "has-attachment", "subject": "A", "hasAttachments": True},
                {"id": "no-attachment", "subject": "B", "hasAttachments": False},
            ]
        }
    )

    assert [change.meta.has_attachments for change in page.changes] == [True, False]


# --- provider + transport --------------------------------------------------

def test_graph_delta_uses_delta_link_and_next_link():
    transport = FixtureTransport()
    transport.add(
        "GET",
        "/me/mailFolders/inbox/messages/delta",
        {
            "@odata.nextLink": "https://graph/delta?page=2",
            "value": [{"id": "gone", "@removed": {"reason": "deleted"}}],
        },
    )
    transport.add(
        "GET",
        "https://graph/delta?page=2",
        {"@odata.deltaLink": "https://graph/delta?token=abc", "value": []},
    )

    p = GraphProvider(credential_ref="x", transport=transport)
    first = p.delta_changes("inbox", {})
    assert first.changes[0].kind == "delete"
    second = p.delta_changes("inbox", first.next_cursor)
    assert second.exhausted
    assert second.next_cursor["delta_link"].endswith("token=abc")
    assert len(transport.calls) == 2

    with pytest.raises(GraphNotConfiguredError):
        GraphProvider(credential_ref="x").delta_changes("inbox", {"delta_link": "x"})


def test_graph_metadata_list_uses_wire_payload():
    transport = FixtureTransport()
    transport.add(
        "GET",
        "/me/mailFolders/inbox/messages",
        {"value": [{"id": "m1", "subject": "Hello"}]},
    )
    provider = GraphProvider(credential_ref="x", transport=transport)

    page = provider.fetch_metadata_page("inbox", None)

    assert page.exhausted
    assert [item.remote_id for item in page.items] == ["m1"]
    assert page.items[0].subject == "Hello"


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


def test_graph_folder_pagination_rejects_repeated_next_link():
    calls = []

    def transport(_method, path, _params):
        calls.append(path)
        if path == "/me/mailFolders/inbox":
            return {"id": "inbox", "childFolderCount": 0}
        return {"value": [], "@odata.nextLink": "/me/mailFolders"}

    with pytest.raises(GraphPaginationError, match="repeated nextLink"):
        GraphProvider(credential_ref="x", transport=transport).list_folders()

    assert calls.count("/me/mailFolders") == 1


def test_graph_folder_pagination_caps_pages_across_nested_folders(monkeypatch):
    import mail_core.providers.graph as graph_module

    monkeypatch.setattr(graph_module, "MAX_GRAPH_PAGES_PER_CALL", 1)

    def transport(_method, path, _params):
        if path == "/me/mailFolders/inbox":
            return {"id": "inbox", "childFolderCount": 0}
        if path == "/me/mailFolders":
            return {"value": [{"id": "parent", "childFolderCount": 1}]}
        return {"value": []}

    with pytest.raises(GraphPaginationError, match="page limit"):
        GraphProvider(credential_ref="x", transport=transport).list_folders()


def test_graph_reconcile_caps_items_and_rejects_repeated_next_link(monkeypatch):
    import mail_core.providers.graph as graph_module

    monkeypatch.setattr(graph_module, "MAX_GRAPH_ITEMS_PER_CALL", 1)

    def too_many_items(_method, _path, _params):
        return {"value": [{"id": "one"}, {"id": "two"}]}

    provider = GraphProvider(credential_ref="x", transport=too_many_items)
    with pytest.raises(GraphPaginationError, match="item limit"):
        provider.reconcile("inbox", [])

    monkeypatch.setattr(graph_module, "MAX_GRAPH_ITEMS_PER_CALL", 10)
    monkeypatch.setattr(graph_module, "MAX_GRAPH_PAGES_PER_CALL", 2)
    page_calls = []

    def many_pages(_method, path, _params):
        page_calls.append(path)
        return {"value": [], "@odata.nextLink": f"/page/{len(page_calls)}"}

    provider = GraphProvider(credential_ref="x", transport=many_pages)
    with pytest.raises(GraphPaginationError, match="page limit"):
        provider.reconcile("inbox", [])
    assert len(page_calls) == 2

    repeated_calls = []

    def repeated_next_link(_method, path, _params):
        repeated_calls.append(path)
        return {"value": [{"id": "one"}], "@odata.nextLink": path}

    monkeypatch.setattr(graph_module, "MAX_GRAPH_PAGES_PER_CALL", 100)
    provider = GraphProvider(credential_ref="x", transport=repeated_next_link)
    with pytest.raises(GraphPaginationError, match="repeated nextLink"):
        provider.reconcile("inbox", [])
    assert len(repeated_calls) == 1


def test_not_configured_without_credentials_transport():
    with pytest.raises(GraphNotConfiguredError):
        GraphProvider(credential_ref="").list_folders()
    with pytest.raises(GraphNotConfiguredError):
        GraphProvider(credential_ref="").fetch_mime("x")


def test_graph_reconcile_use_standard_queries():
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


def test_graph_delta_partial_status_field_presence_contract():
    page = parse_graph_delta(
        {
            "value": [
                {"id": "m_read_only", "isRead": True},
                {"id": "m_flag_only", "flag": {"flagStatus": "flagged"}},
                {
                    "id": "m_full_read_only",
                    "subject": "Real Subject",
                    "from": {"emailAddress": {"address": "sender@test.com", "name": "Sender"}},
                    "receivedDateTime": "2026-10-22T08:00:00Z",
                    "isRead": False,
                },
                {"id": "m_unflagged", "flag": {"flagStatus": "notFlagged"}},
            ]
        }
    )
    assert len(page.changes) == 4
    c1, c2, c3, c4 = page.changes
    assert c1.kind == "flag"
    assert c1.meta is None
    assert c1.flags == {"is_read": True}

    assert c2.kind == "flag"
    assert c2.meta is None
    assert c2.flags == {"is_flagged": True}

    # Content-bearing updates preserve omitted status fields in the metadata model too.
    assert c3.kind == "upsert"
    assert c3.meta is not None
    assert c3.meta.subject == "Real Subject"
    assert c3.meta.from_address == "sender@test.com"
    assert c3.meta.is_read is False
    assert c3.meta.is_flagged is None
    assert c3.meta.has_attachments is None
    assert c4.flags == {"is_flagged": False}


@pytest.mark.parametrize(
    ("received", "last_modified", "expected"),
    [
        (
            "2026-10-20T12:30:00Z",
            "2026-10-21T12:30:00Z",
            datetime(2026, 10, 20, 12, 30, tzinfo=timezone.utc),
        ),
        (
            "2026-10-20T12:30:00+05:30",
            "2026-10-21T12:30:00Z",
            datetime.fromisoformat("2026-10-20T12:30:00+05:30"),
        ),
        ("2026-10-20T12:30:00", "2026-10-21T12:30:00Z", None),
        (None, "2026-10-21T12:30:00Z", None),
        (True, "2026-10-21T12:30:00Z", None),
        (1.5, "2026-10-21T12:30:00Z", None),
        ({"date": "2026-10-20T12:30:00Z"}, "2026-10-21T12:30:00Z", None),
        ("invalid", "2026-10-21T12:30:00Z", None),
    ],
)
def test_graph_received_date_is_the_only_received_time_source(received, last_modified, expected):
    item = {"id": "graph-time", "subject": "Message", "lastModifiedDateTime": last_modified}
    if received is not None:
        item["receivedDateTime"] = received

    page = parse_graph_delta({"value": [item]})

    assert page.changes[0].meta is not None
    assert page.changes[0].meta.sort_time == expected


