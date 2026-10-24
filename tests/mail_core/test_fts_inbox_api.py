from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from mail_core.accounts import create_account
from mail_core.api.app import app
from tests.mail_core.conftest import TEST_API_KEY
from mail_core.db.session import get_session_factory
from mail_core.mail.storage import Folder, FolderStats, Message, MessageLocation, MessageSearch, Thread
from mail_core.search.index import upsert_message_search
from mail_core.threading.rules import assign_thread_for_message, normalize_subject

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_unified_inbox_folder_stats_search_and_thread():
    Session = get_session_factory()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc = create_account(
            session,
            email=f"api-{uuid.uuid4().hex[:8]}@ex.com",
            provider="imap",
            config={"imap_host": "8.8.8.8"},
        )
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        m1 = Message(
            account_id=acc.id,
            remote_id="1",
            subject="Hello Project Phoenix",
            from_address="alice@ex.com",
            from_name="Alice",
            sort_time=now,
            is_read=False,
            snippet="discuss phoenix roadmap",
            internet_message_id="<m1@ex.com>",
        )
        session.add(m1)
        session.flush()
        session.add(MessageLocation(message_id=m1.id, folder_id=folder.id, uid=1))
        session.add(FolderStats(folder_id=folder.id, total_count=1, unread_count=1))
        upsert_message_search(session, message_id=m1.id, body_text="discuss phoenix roadmap")
        assign_thread_for_message(session, message=m1)
        session.commit()
        account_id = acc.id
        folder_id = folder.id
        message_id = m1.id

    inbox = client.get("/api/mail/inbox", params={"account_id": str(account_id)})
    assert inbox.status_code == 200
    body = inbox.json()
    assert any(i["id"] == str(message_id) for i in body["items"])

    stats = client.get(f"/api/mail/accounts/{account_id}/folder-stats")
    assert stats.status_code == 200
    assert stats.json()["folders"][0]["unread_count"] == 1

    one = client.get(f"/api/mail/folders/{folder_id}/stats")
    assert one.status_code == 200
    assert one.json()["total_count"] == 1

    global_stats = client.get("/api/mail/stats")
    assert global_stats.status_code == 200
    gs_json = global_stats.json()
    assert "total_unread" in gs_json
    assert "accounts" in gs_json
    acc_entry = next((a for a in gs_json["accounts"] if a["account_id"] == str(account_id)), None)
    assert acc_entry is not None
    assert acc_entry["unread_count"] == 1
    assert acc_entry["total_count"] == 1
    assert gs_json["total_unread"] >= 1

    search = client.get("/api/mail/search", params={"q": "phoenix", "account_id": str(account_id)})
    assert search.status_code == 200
    sj = search.json()
    assert sj["total"] >= 1 and sj["offset"] == 0
    hit = next(i for i in sj["items"] if i["id"] == str(message_id))
    assert hit["subject"] and "is_flagged" in hit

    bad = client.get("/api/mail/inbox", params={"cursor": "%%%not-a-cursor"})
    assert bad.status_code == 400

    assert normalize_subject("Re: Hello") == "hello"
    with Session() as session:
        msg = session.get(Message, message_id)
        thread = session.get(Thread, msg.thread_id)
        assert thread.account_id == msg.account_id
        assert thread.subject_norm == normalize_subject("Hello Project Phoenix")
        row = session.get(MessageSearch, message_id)
        assert "Phoenix" in row.subject


def test_list_body_preview_is_read_only_and_preserves_provider_snippets():
    from sqlalchemy import event
    from mail_core.mail.application.queries import messages_by_ids
    from mail_core.mail.storage import MessageBody

    Session = get_session_factory()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    cases = [
        ("  Provider <raw@example.com> &amp; text  ", "Body must not replace provider", None, None, ""),
        (None, "Plain   body\npreview", None, None, "Plain body preview"),
        (None, "Use <div> &amp; <support@example.com> literally", None, None, "Use <div> &amp; <support@example.com> literally"),
        ("", None, "<html><head><title>Hidden</title><style>Hidden</style></head><body><p>HTML &amp; body</p><script>Hidden</script></body></html>", None, "HTML & body"),
        (None, None, None, None, ""),
        (None, "x" * 300, None, None, "x" * 180),
    ]
    with Session() as session:
        account = create_account(
            session,
            email="preview@example.com",
            provider="imap",
            config={"imap_host": "8.8.8.8"},
        )
        folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        ids = []
        for i, (snippet, plain, html, error, _) in enumerate(cases):
            message = Message(account_id=account.id, remote_id=str(i), subject="PreviewCase", from_address="sender@example.com", sort_time=datetime.now(timezone.utc), snippet=snippet)
            session.add(message)
            session.flush()
            ids.append(message.id)
            session.add(MessageLocation(message_id=message.id, folder_id=folder.id, uid=i + 1))
            if plain is not None or html is not None:
                session.add(MessageBody(message_id=message.id, text_plain=plain, text_html=html, parse_error=error))
            upsert_message_search(session, message_id=message.id, body_text="PreviewCase")
        session.commit()
        account_id = str(account.id)

    for path, params in [("/api/mail/inbox", {}), ("/api/mail/search", {"q": "PreviewCase"})]:
        response = client.get(path, params={"account_id": account_id, **params})
        assert response.status_code == 200
        rows = {row["id"]: row for row in response.json()["items"]}
        for mid, (snippet, _, _, _, expected) in zip(ids, cases):
            assert rows[str(mid)]["snippet"] == snippet
            assert rows[str(mid)]["body_preview"] == expected

    with Session() as session:
        statements = []

        def capture(connection, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(session.get_bind(), "before_cursor_execute", capture)
        try:
            items = messages_by_ids(session, ids)
        finally:
            event.remove(session.get_bind(), "before_cursor_execute", capture)
        assert [item.id for item in items] == ids
        assert len(statements) == 2  # metadata + one body batch, regardless of page size
        session.commit()
        for mid, (snippet, _, _, _, _) in zip(ids, cases):
            assert session.get(Message, mid).snippet == snippet


# The previous combined test incorrectly excluded readable partial text; conventions §9.3 allows it with parse_error.
def test_list_body_preview_keeps_readable_partial_body_when_parse_error_exists():
    from mail_core.mail.storage import MessageBody

    Session = get_session_factory()
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    with Session() as session:
        account = create_account(
            session,
            email="partial-preview@example.com",
            provider="imap",
            config={"imap_host": "8.8.8.8"},
        )
        folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        message = Message(
            account_id=account.id,
            remote_id="partial",
            subject="PartialPreview",
            from_address="sender@example.com",
            sort_time=datetime.now(timezone.utc),
            snippet=None,
        )
        session.add(message)
        session.flush()
        session.add(MessageLocation(message_id=message.id, folder_id=folder.id, uid=1))
        session.add(MessageBody(message_id=message.id, text_plain="Partial", parse_error="parse failed"))
        upsert_message_search(session, message_id=message.id, body_text="PartialPreview")
        session.commit()
        account_id, message_id = str(account.id), message.id

    for path, params in [("/api/mail/inbox", {}), ("/api/mail/search", {"q": "PartialPreview"})]:
        response = client.get(path, params={"account_id": account_id, **params})
        assert response.status_code == 200
        row = next(item for item in response.json()["items"] if item["id"] == str(message_id))
        assert row["snippet"] is None
        assert row["body_preview"] == "Partial"

    with Session() as session:
        assert session.get(Message, message_id).snippet is None
