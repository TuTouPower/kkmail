from __future__ import annotations

import os
import uuid

import pytest

from mail_core.providers.gmail import GmailProvider
from mail_core.providers.parsing.graph_delta import parse_graph_delta


@pytest.mark.parametrize("detail", [{}, {"id": "m"}, {"id": "other", "labelIds": [], "payload": {"headers": []}}])
@pytest.mark.parametrize("delta", [False, True])
def test_gmail_rejects_incomplete_or_mismatched_hydration(detail, delta):
    def transport(method, path, params):
        if path.endswith('/profile'):
            return {"historyId": "1"}
        if path.endswith('/history'):
            return {"historyId": "2", "history": [{"messagesAdded": [{"message": {"id": "m", "subject": "partial"}}]}]}
        if path.endswith('/messages'):
            return {"messages": [{"id": "m"}]}
        return detail

    provider = GmailProvider(credential_ref="test", transport=transport)
    with pytest.raises(ValueError, match="metadata"):
        if delta:
            provider.delta_changes("INBOX", {"historyId": "1"})
        else:
            provider.fetch_metadata_page("INBOX", None)


def test_gmail_hydration_failure_never_uses_partial_history_headers():
    def transport(method, path, params):
        if path.endswith('/history'):
            return {"historyId": "2", "history": [{"messagesAdded": [{"message": {"id": "m", "subject": "partial"}}]}]}
        raise RuntimeError("detail unavailable")

    with pytest.raises(RuntimeError, match="detail unavailable"):
        GmailProvider(credential_ref="test", transport=transport).delta_changes("INBOX", {"historyId": "1"})


@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="MAIL_CORE_DATABASE_URL not set")
def test_partial_graph_and_gmail_updates_preserve_omissions_and_apply_explicit_empty():
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage import Account, Folder, Message
    from mail_core.sync.metadata import upsert_messages

    with get_session_factory()() as session:
        account = Account(email=f"partial-{uuid.uuid4().hex}@example.com", provider="graph")
        session.add(account)
        session.flush()
        folder = Folder(account_id=account.id, remote_id="inbox", name="Inbox", role="inbox")
        session.add(folder)
        session.flush()
        message = Message(account_id=account.id, remote_id="m", subject="old", from_address="a@example.com", from_name="Alice", snippet="provider snippet", internet_message_id="<id>", to_addresses=["to@example.com"], cc_addresses=["cc@example.com"], is_read=True, is_flagged=True, has_attachments=True)
        session.add(message)
        session.flush()

        def apply(item):
            page = parse_graph_delta({"value": [item]})
            assert page.changes[0].kind == "upsert"
            upsert_messages(session, account_id=account.id, folder_id=folder.id, metas=[page.changes[0].meta])
            session.expire(message)

        apply({"id": "m", "subject": "new"})
        assert message.subject == "new"
        assert (message.from_address, message.from_name, message.snippet, message.internet_message_id) == ("a@example.com", "Alice", "provider snippet", "<id>")
        assert message.to_addresses == ["to@example.com"]
        assert message.cc_addresses == ["cc@example.com"]
        apply({"id": "m", "from": {"emailAddress": {"address": "b@example.com", "name": "Bob"}}})
        assert message.subject == "new"
        assert message.from_name == "Bob"
        assert message.snippet == "provider snippet"

        def transport(method, path, params):
            if path.endswith('/profile'):
                return {"historyId": "1"}
            if path.endswith('/messages'):
                return {"messages": [{"id": "m"}]}
            if path.endswith('/history'):
                return {"historyId": "2", "history": [{"messagesAdded": [{"message": {"id": "m"}}]}]}
            return {"id": "m", "labelIds": ["INBOX"], "payload": {"headers": [{"name": "Subject", "value": "Gmail"}]}}

        provider = GmailProvider(credential_ref="test", transport=transport)
        for meta in [provider.fetch_metadata_page("INBOX", None).items[0], provider.delta_changes("INBOX", {"historyId": "1"}).changes[0].meta]:
            upsert_messages(session, account_id=account.id, folder_id=folder.id, metas=[meta])
            session.expire(message)
            assert message.snippet == "provider snippet"
            assert message.subject == "Gmail"
            assert message.is_read is True
            assert message.is_flagged is False
            assert message.has_attachments is True
        from dataclasses import replace
        inserted = upsert_messages(
            session, account_id=account.id, folder_id=folder.id,
            metas=[replace(meta, remote_id="new-without-snippet")],
        )[0].message
        session.expire(inserted)
        assert inserted.snippet is None
        apply({"id": "m", "subject": "", "bodyPreview": "", "from": None, "toRecipients": [], "ccRecipients": [], "internetMessageId": None, "hasAttachments": False})
        assert message.subject == message.from_address == message.snippet == ""
        assert message.from_name is None and message.internet_message_id is None
        assert message.to_addresses == message.cc_addresses == []
        assert message.has_attachments is False


@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="MAIL_CORE_DATABASE_URL not set")
@pytest.mark.parametrize("items,subject,snippet,is_read", [
    ([{"subject": "new"}, {"bodyPreview": "preview"}], "new", "preview", True),
    ([{"isRead": False}, {"subject": "new"}], "new", "old preview", False),
    ([{"subject": "new"}, {"isRead": False}, {"bodyPreview": "preview"}], "new", "preview", False),
    ([{"isRead": False}, {"_complete_snapshot": True, "subject": "new", "bodyPreview": "old preview", "from": {"emailAddress": {"address": "sender@example.com"}}}], "new", "old preview", False),
    ([{"subject": "discard"}, {"@removed": {}}, {"subject": "new"}], "new", "old preview", True),
])
def test_delta_application_combines_partial_changes_in_response_order(items, subject, snippet, is_read):
    from datetime import timedelta
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage import Account, Folder, Message, MessageLocation
    from mail_core.sync import acquire_lease
    from mail_core.sync.delta import apply_delta_page

    with get_session_factory()() as session:
        account = Account(email=f"delta-partial-{uuid.uuid4().hex}@example.com", provider="graph")
        session.add(account)
        session.flush()
        folder = Folder(account_id=account.id, remote_id="inbox", name="Inbox", role="inbox")
        session.add(folder)
        session.flush()
        message = Message(account_id=account.id, remote_id="m", subject="old", from_address="sender@example.com", snippet="old preview", is_read=True, is_flagged=False, has_attachments=False)
        session.add(message)
        session.flush()
        session.add(MessageLocation(message_id=message.id, folder_id=folder.id))
        lease = acquire_lease(session, account_id=account.id, owner_id="partial", ttl=timedelta(minutes=5))
        page = parse_graph_delta({"value": [{"id": "m", **item} for item in items], "@odata.deltaLink": "next"})
        if any(item.get("_complete_snapshot") for item in items):
            from dataclasses import replace
            last = page.changes[-1]
            page = replace(page, changes=[*page.changes[:-1], replace(last, meta=replace(last.meta, supplied_fields=None))])
        apply_delta_page(session, account_id=account.id, folder_id=folder.id, fencing_token=lease.fencing_token, page=page)
        session.flush()
        session.expire(message)
        assert (message.subject, message.snippet, message.is_read) == (subject, snippet, is_read)
        assert message.from_address == "sender@example.com"
