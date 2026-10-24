import pytest

from mail_core.providers.gmail import GmailProvider
from mail_core.providers.http import ProviderHttpError


def _detail(message_id: str) -> dict:
    return {
        "id": message_id,
        "labelIds": ["INBOX"],
        "payload": {"headers": [{"name": "Subject", "value": "subject"}]},
    }


def test_metadata_page_skips_404_only_after_reconcile_confirms_absence(caplog):
    calls = []

    def transport(method, path, params=None):
        params = params or {}
        calls.append((method, path, params))
        if path.endswith("/messages"):
            if params.get("maxResults") == 500:
                return {"messages": [{"id": "live"}]}
            return {"messages": [{"id": "gone"}, {"id": "live"}], "nextPageToken": "next"}
        if path.endswith("/messages/gone"):
            raise ProviderHttpError("message not found", status=404, body={"error": {"message": "not found"}})
        if path.endswith("/messages/live"):
            return _detail("live")
        raise AssertionError(f"unexpected {method} {path}")

    page = GmailProvider(credential_ref="cred", transport=transport).fetch_metadata_page(
        "INBOX", {"historyId": "7", "pageToken": "page-1"}
    )

    assert [item.remote_id for item in page.items] == ["live"]
    assert page.next_cursor == {"pageToken": "next", "historyId": "7"}
    assert page.exhausted is False
    assert sum(1 for _, path, params in calls if path.endswith("/messages") and params.get("maxResults") == 500) == 1
    assert "deleted before detail fetch" in caplog.text


def test_metadata_page_keeps_404_failure_when_reconcile_still_lists_message():
    def transport(method, path, params=None):
        params = params or {}
        if path.endswith("/messages"):
            if params.get("maxResults") == 500:
                return {"messages": [{"id": "gone"}]}
            return {"messages": [{"id": "gone"}], "nextPageToken": "next"}
        if path.endswith("/messages/gone"):
            raise ProviderHttpError("message not found", status=404, body={"error": {"message": "not found"}})
        raise AssertionError(f"unexpected {method} {path}")

    with pytest.raises(ProviderHttpError, match="message not found"):
        GmailProvider(credential_ref="cred", transport=transport).fetch_metadata_page(
            "INBOX", {"historyId": "7", "pageToken": "page-1"}
        )


def test_metadata_page_does_not_reconcile_other_get_errors():
    reconcile_calls = 0

    def transport(method, path, params=None):
        nonlocal reconcile_calls
        params = params or {}
        if path.endswith("/messages"):
            if params.get("maxResults") == 500:
                reconcile_calls += 1
                return {"messages": []}
            return {"messages": [{"id": "m1"}], "nextPageToken": "next"}
        if path.endswith("/messages/m1"):
            raise ProviderHttpError("temporary failure", status=503)
        raise AssertionError(f"unexpected {method} {path}")

    with pytest.raises(ProviderHttpError, match="temporary failure"):
        GmailProvider(credential_ref="cred", transport=transport).fetch_metadata_page(
            "INBOX", {"historyId": "7", "pageToken": "page-1"}
        )
    assert reconcile_calls == 0


def test_metadata_page_keeps_malformed_details_as_page_failures():
    reconcile_calls = 0

    def transport(method, path, params=None):
        nonlocal reconcile_calls
        params = params or {}
        if path.endswith("/messages"):
            if params.get("maxResults") == 500:
                reconcile_calls += 1
                return {"messages": []}
            return {"messages": [{"id": "m1"}], "nextPageToken": "next"}
        if path.endswith("/messages/m1"):
            return {"id": "other", "labelIds": [], "payload": {"headers": []}}
        raise AssertionError(f"unexpected {method} {path}")

    with pytest.raises(ValueError, match="incomplete or has mismatched id"):
        GmailProvider(credential_ref="cred", transport=transport).fetch_metadata_page(
            "INBOX", {"historyId": "7", "pageToken": "page-1"}
        )
    assert reconcile_calls == 0


def test_delta_hydration_converts_confirmed_deleted_404_to_delete_change():
    def transport(method, path, params=None):
        params = params or {}
        if path.endswith("/history"):
            return {
                "history": [
                    {"id": "8", "messagesAdded": [{"message": {"id": "gone", "labelIds": ["INBOX"]}}]}
                ],
                "historyId": "9",
            }
        if path.endswith("/messages/gone"):
            raise ProviderHttpError("message not found", status=404, body={"error": {"message": "not found"}})
        if path.endswith("/messages"):
            return {"messages": []}
        raise AssertionError(f"unexpected {method} {path}")

    page = GmailProvider(credential_ref="cred", transport=transport).delta_changes("INBOX", {"historyId": "7"})

    assert [(change.kind, change.remote_id) for change in page.changes] == [("delete", "gone")]
    assert page.next_cursor == {"historyId": "9"}
    assert page.exhausted is True


def test_delta_page_keeps_malformed_details_as_page_failures():
    reconcile_calls = 0

    def transport(method, path, params=None):
        nonlocal reconcile_calls
        params = params or {}
        if path.endswith("/history"):
            return {
                "history": [
                    {"id": "8", "messagesAdded": [{"message": {"id": "m1", "labelIds": ["INBOX"]}}]}
                ],
                "historyId": "9",
            }
        if path.endswith("/messages/m1"):
            return {"id": "other", "labelIds": [], "payload": {"headers": []}}
        if path.endswith("/messages"):
            reconcile_calls += 1
            return {"messages": []}
        raise AssertionError(f"unexpected {method} {path}")

    with pytest.raises(ValueError, match="incomplete or has mismatched id"):
        GmailProvider(credential_ref="cred", transport=transport).delta_changes("INBOX", {"historyId": "7"})
    assert reconcile_calls == 0
