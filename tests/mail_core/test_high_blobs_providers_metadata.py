"""High-finding coverage: blobs GC/rotate, Gmail metadata, Graph trash, IMAP MODSEQ, reclaim."""

from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta, timezone

import pytest

from mail_core.blobs.crypto import load_keyring_from_env
from mail_core.blobs.rotate import rewrap_blob_file
from mail_core.blobs.store import BlobStore
from mail_core.mail.application.remote_ops import reclaim_stale_in_progress
from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.providers.gmail import GmailProvider, _meta_from_gmail_message
from mail_core.providers.graph import GraphProvider
from mail_core.providers.http import ProviderHttpError, RateLimitedError
from mail_core.providers.imap import ImapProvider, format_imap_remote_id
from mail_core.sync.metadata import apply_metadata_page
from mail_core.providers.base import MetadataPage, RemoteMessageMeta


def test_gmail_fetch_metadata_page_batches_messages_get():
    calls: list[tuple[str, str, dict]] = []

    def transport(method, path, params=None):
        params = params or {}
        calls.append((method, path, params))
        if path.endswith("/messages") and "messages/" not in path.rstrip("/").split("/")[-1]:
            return {
                "messages": [{"id": "m1", "threadId": "t1"}, {"id": "m2", "threadId": "t2"}],
                "nextPageToken": None,
            }
        if "/messages/m1" in path:
            return {
                "id": "m1",
                "threadId": "t1",
                "labelIds": ["INBOX", "UNREAD"],
                "internalDate": "1710000000000",
                "snippet": "hi",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Hello"},
                        {"name": "From", "value": "Ann <ann@ex.com>"},
                        {"name": "Message-ID", "value": "<m1@ex.com>"},
                        {"name": "In-Reply-To", "value": "<root@ex.com>"},
                        {"name": "References", "value": "<root@ex.com>"},
                    ]
                },
            }
        if "/messages/m2" in path:
            return {
                "id": "m2",
                "threadId": "t2",
                "labelIds": ["INBOX"],
                "internalDate": "1710000001000",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "World"},
                        {"name": "From", "value": "bob@ex.com"},
                    ]
                },
            }
        if path.endswith("/profile"):
            return {"historyId": "999"}
        raise AssertionError(f"unexpected {method} {path}")

    p = GmailProvider(credential_ref="x", transport=transport)
    page = p.fetch_metadata_page("INBOX", None)
    assert page.exhausted
    assert page.next_cursor and page.next_cursor.get("historyId") == "999"
    assert len(page.items) == 2
    assert page.items[0].subject == "Hello"
    assert page.items[0].from_address == "ann@ex.com"
    assert page.items[0].in_reply_to == "<root@ex.com>"
    assert page.items[0].references == "<root@ex.com>"
    assert page.items[1].subject == "World"
    assert any("/messages/m1" in c[1] for c in calls)
    assert any(c[2].get("format") == "metadata" for c in calls if "/messages/m" in c[1])


def test_meta_from_gmail_message_headers():
    meta = _meta_from_gmail_message(
        {
            "id": "x",
            "threadId": "t",
            "labelIds": ["UNREAD"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "S"},
                    {"name": "From", "value": "a@b.c"},
                    {"name": "In-Reply-To", "value": "<p@e>"},
                ]
            },
        }
    )
    assert meta.subject == "S" and meta.in_reply_to == "<p@e>" and meta.is_read is False


def test_graph_trash_does_not_swallow_rate_limit():
    def transport(method, path, params=None):
        if method == "POST" and path.endswith("/move"):
            raise RateLimitedError("slow down", retry_after_seconds=30)
        raise AssertionError("DELETE must not run after rate limit")

    p = GraphProvider(credential_ref="x", transport=transport)
    with pytest.raises(RateLimitedError):
        p.apply_remote_operation("trash", {"remote_id": "m1"})


def test_graph_trash_falls_back_to_delete_on_other_http_error():
    seen: list[str] = []

    def transport(method, path, params=None):
        seen.append(method)
        if method == "POST" and path.endswith("/move"):
            raise ProviderHttpError("no trash folder", status=404)
        if method == "DELETE":
            return {}
        raise AssertionError(path)

    p = GraphProvider(credential_ref="x", transport=transport)
    r = p.apply_remote_operation("trash", {"remote_id": "m1"})
    assert r.success and r.remote_state.get("deleted")
    assert seen == ["POST", "DELETE"]


def test_imap_modseq_emits_flag_changes(monkeypatch):
    """MODSEQ SEARCH results must become flag DeltaChanges, not be discarded."""

    class FakeImap:
        def __init__(self):
            self._folder = None

        def login(self, *a):
            return "OK", []

        def logout(self):
            return "OK", []

        def select(self, folder, readonly=True):
            self._folder = folder
            return "OK", [b"1"]

        def status(self, folder, items):
            return "OK", [b"INBOX (UIDVALIDITY 7 HIGHESTMODSEQ 50)"]

        def uid(self, cmd, *args):
            if cmd == "SEARCH":
                # MODSEQ search → UID 5 changed flags
                return "OK", [b"5"]
            if cmd == "FETCH":
                uid = args[0]
                if "FLAGS" in str(args[1]) and "HEADER" not in str(args[1]):
                    return "OK", [(b"5 (FLAGS (\\Seen \\Flagged) UID 5)", b"")]
                # full metadata path
                return "OK", [
                    (
                        b"10 (FLAGS (\\Seen) UID 10",
                        b"From: a@b.c\r\nSubject: New\r\nDate: Wed, 21 Oct 2026 01:00:00 +0000\r\nMessage-ID: <n@e>\r\n\r\n",
                    )
                ]
            return "NO", []

    def fake_connect(self):
        return FakeImap()

    monkeypatch.setattr(ImapProvider, "_connect", fake_connect)
    p = ImapProvider(host="h", port=993, username="u", password="p")
    page = p.delta_changes("INBOX", {"modseq": 40, "uidvalidity": 7, "uid_next": 10})
    assert any(c.kind == "flag" for c in page.changes)
    flag = next(c for c in page.changes if c.kind == "flag")
    assert flag.flags.get("is_read") is True
    assert flag.flags.get("is_flagged") is True
    assert page.next_cursor.get("modseq") == 50
    rid = format_imap_remote_id("INBOX", 7, 5)
    assert flag.remote_id == rid


def test_imap_delta_changes_capping_and_pagination(monkeypatch):
    class FakeImapBulk:
        def select(self, folder, readonly=True):
            return "OK", [b"1"]

        def status(self, folder, query):
            return "OK", [b'INBOX (HIGHESTMODSEQ 100 UIDVALIDITY 7)']

        def logout(self):
            return "OK", []

        def uid(self, cmd, *args):
            if cmd == "SEARCH":
                # Return 250 flag UIDs (< 1000)
                uids_bytes = b" ".join(str(i).encode() for i in range(1, 251))
                return "OK", [uids_bytes]
            if cmd == "FETCH":
                return "OK", [(b"1 (FLAGS (\\Seen) UID 1)", b"")]
            return "NO", []

    monkeypatch.setattr(ImapProvider, "_connect", lambda self: FakeImapBulk())
    p = ImapProvider(host="h", port=993, username="u", password="p")
    # First page: 250 flag changes capped at 200, modseq NOT bumped to 100
    page1 = p.delta_changes("INBOX", {"modseq": 40, "uidvalidity": 7, "uid_next": 1000})
    assert len(page1.changes) == 200
    assert not page1.exhausted
    assert page1.next_cursor.get("modseq") == 40
    assert page1.next_cursor.get("flag_uid_after") == 200

    # Second page: process remaining 50 flag changes, now exhausted and modseq bumped
    page2 = p.delta_changes("INBOX", page1.next_cursor)
    assert len(page2.changes) == 50
    assert page2.exhausted
    assert page2.next_cursor.get("modseq") == 100
    assert "flag_uid_after" not in page2.next_cursor


def test_rewrap_cleans_tmp_on_failure(tmp_path, monkeypatch):
    k1 = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setenv("MAIL_CORE_BLOB_KEYS", f'{{"1": "{k1}"}}')
    monkeypatch.setenv("MAIL_CORE_BLOB_ACTIVE_VERSION", "1")
    store = BlobStore(tmp_path)
    put = store.put(b"data")
    path = store.path_for(put.content_sha256)
    # Corrupt so unwrap fails mid-rewrap to v2 missing key
    monkeypatch.setenv("MAIL_CORE_BLOB_KEYS", f'{{"1": "{k1}", "2": "{base64.b64encode(os.urandom(32)).decode()}"}}')
    monkeypatch.setenv("MAIL_CORE_BLOB_ACTIVE_VERSION", "2")
    keyring = load_keyring_from_env()
    # Truncate file to force failure during unwrap
    path.write_bytes(path.read_bytes()[:8])
    with pytest.raises(Exception):
        rewrap_blob_file(path, keyring=keyring)
    assert not list(tmp_path.rglob("*.rewrap"))


@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="PG required")
def test_reclaim_stale_in_progress_and_metadata_history_checkpoint():
    from mail_core.db.session import get_session_factory
    from mail_core.mail.application.remote_ops import enqueue_remote_operation, mark_remote_operation
    from mail_core.mail.storage import Account, Folder, RemoteOperation, SyncCheckpoint
    from mail_core.sync import acquire_lease
    from sqlalchemy import select

    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"hi-{os.urandom(4).hex()}@example.com", provider="gmail")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()
        op = enqueue_remote_operation(
            session,
            account_id=acc.id,
            entity_key="m:1",
            op_type="mark_read",
            desired_state={"is_read": True},
            idempotency_key=f"idem-{os.urandom(4).hex()}",
        )
        mark_remote_operation(session, op, status=RemoteOperationStatus.IN_PROGRESS)
        op.updated_at = datetime.now(timezone.utc) - timedelta(hours=1)
        session.commit()

        n = reclaim_stale_in_progress(session, older_than=timedelta(minutes=15))
        session.commit()
        assert n >= 1
        loaded = session.get(RemoteOperation, op.id)
        assert loaded.status == "pending"

        lease = acquire_lease(session, account_id=acc.id, owner_id="t", ttl=timedelta(minutes=5))
        page = MetadataPage(
            items=[
                RemoteMessageMeta(
                    remote_id="gm1",
                    subject="S",
                    from_address="a@b.c",
                    from_name=None,
                    sort_time=datetime.now(timezone.utc),
                    is_read=False,
                    has_attachments=False,
                    internet_message_id="<gm1@ex.com>",
                    in_reply_to="<root@ex.com>",
                )
            ],
            next_cursor={"historyId": "4242"},
            exhausted=True,
        )
        apply_metadata_page(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=page,
        )
        session.commit()
        cp = session.get(SyncCheckpoint, {"account_id": acc.id, "folder_id": folder.id})
        assert cp is not None
        assert cp.history_id == "4242"
