from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from mail_core.mail.application.mutations import mark_all_messages_read
from mail_core.mail.application.queries import list_folder_stats_for_account, unified_inbox
from mail_core.mail.storage.models import Account, Folder, FolderStats, Message, MessageLocation
from mail_core.providers.base import RemoteFolder
from mail_core.providers.imap import ImapProvider, decode_mutf7


# --- AC-006: IMAP SPECIAL-USE 标志与中文名称映射、Modified UTF-7 解码 ---


def test_decode_mutf7_common_chinese_folders():
    assert decode_mutf7("&XfJT0ZAB-") == "已发送"
    assert decode_mutf7("&g0l6P3ux-") == "草稿箱"
    assert decode_mutf7("&Xp9+uHvT-") == "废纸篓"
    assert decode_mutf7("&V4NXPpCuTvY-") == "垃圾邮件"
    assert decode_mutf7("&X1JoYw-") == "归档"
    assert decode_mutf7("&-") == "&"
    assert decode_mutf7("Inbox") == "Inbox"
    assert decode_mutf7("Plain English") == "Plain English"


def test_imap_list_folders_special_use_and_mutf7_priority(monkeypatch):
    class FakeIMAPSpecialUse:
        def list(self):
            return "OK", [
                b'(\\HasNoChildren) "/" "INBOX"',
                # SPECIAL-USE flags
                b'(\\HasNoChildren \\Sent) "/" "CustomSent"',
                b'(\\HasNoChildren \\Drafts) "/" "MyDrafts"',
                b'(\\HasNoChildren \\Trash) "/" "TrashBin"',
                b'(\\HasNoChildren \\Junk) "/" "SpamFolder"',
                b'(\\HasNoChildren \\Archive) "/" "OldStuff"',
                # Conflict: flag \\Sent but name says "Trash" -> flag wins
                b'(\\HasNoChildren \\Sent) "/" "Trash"',
                # Modified UTF-7 Chinese names without flags
                b'(\\HasNoChildren) "/" "&XfJT0ZAB-"', # 已发送
                b'(\\HasNoChildren) "/" "&g0l6P3ux-"', # 草稿箱
                b'(\\HasNoChildren) "/" "&Xp9+uHvT-"', # 废纸篓
                b'(\\HasNoChildren) "/" "&V4NXPpCuTvY-"', # 垃圾邮件
                b'(\\HasNoChildren) "/" "&X1JoYw-"', # 归档
                # Hierarchical folder with delimiter
                b'(\\HasChildren) "/" "Work"',
                b'(\\HasNoChildren) "/" "Work/ProjectA"',
                # Other custom folder
                b'(\\HasNoChildren) "/" "Personal"',
            ]

        def logout(self):
            return "OK", []

    prov = ImapProvider("imap.example.com", 993, "user", "pass", use_ssl=False)
    monkeypatch.setattr(prov, "_connect", lambda: FakeIMAPSpecialUse())
    folders = prov.list_folders()

    folder_map = {f.remote_id: f for f in folders}

    # 1. INBOX is inbox
    assert folder_map["INBOX"].role == "inbox"
    assert folder_map["INBOX"].name == "INBOX"

    # 2. SPECIAL-USE flags mapped
    assert folder_map["CustomSent"].role == "sent"
    assert folder_map["MyDrafts"].role == "drafts"
    assert folder_map["TrashBin"].role == "trash"
    assert folder_map["SpamFolder"].role == "junk"
    assert folder_map["OldStuff"].role == "archive"

    # 3. Conflict: flag takes priority over name
    assert folder_map["Trash"].role == "sent"

    # 4. Modified UTF-7: decoded name is Chinese, remote_id preserved, role mapped
    assert folder_map["&XfJT0ZAB-"].name == "已发送"
    assert folder_map["&XfJT0ZAB-"].role == "sent"

    assert folder_map["&g0l6P3ux-"].name == "草稿箱"
    assert folder_map["&g0l6P3ux-"].role == "drafts"

    assert folder_map["&Xp9+uHvT-"].name == "废纸篓"
    assert folder_map["&Xp9+uHvT-"].role == "trash"

    assert folder_map["&V4NXPpCuTvY-"].name == "垃圾邮件"
    assert folder_map["&V4NXPpCuTvY-"].role == "junk"

    assert folder_map["&X1JoYw-"].name == "归档"
    assert folder_map["&X1JoYw-"].role == "archive"

    # 5. Parent remote ID parsing from hierarchy
    assert folder_map["Work"].parent_remote_id is None
    assert folder_map["Work/ProjectA"].parent_remote_id == "Work"

    # 6. Unmatched custom folder is other
    assert folder_map["Personal"].role == "other"
    assert folder_map["Personal"].name == "Personal"


def test_imap_deleted_messages_is_trash_role(monkeypatch):
    class FakeIMAPDeletedMessages:
        def list(self):
            return "OK", [
                b'(\\HasNoChildren) "/" "INBOX"',
                b'(\\HasNoChildren) "/" "Deleted Messages"',
            ]

        def logout(self):
            return "OK", []

    provider = ImapProvider("imap.example.com", 993, "user", "pass", use_ssl=False)
    monkeypatch.setattr(provider, "_connect", lambda: FakeIMAPDeletedMessages())

    folders = {folder.remote_id: folder for folder in provider.list_folders()}

    assert folders["Deleted Messages"].role == "trash"


# --- AC-004 & AC-005 & AC-007: 精确 folder_id 查询、分页多位置去重与单目录批量已读 ---


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_folder_id_query_dedup_and_mark_read_scope():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        # Create 2 accounts
        acc1 = Account(email=f"f1-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        acc2 = Account(email=f"f2-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add_all([acc1, acc2])
        session.flush()

        # Account 1 folders: Inbox, Drafts, FolderA, FolderB (both other), EmptyFolder
        f_inbox = Folder(account_id=acc1.id, remote_id="INBOX", name="INBOX", role="inbox")
        f_drafts = Folder(account_id=acc1.id, remote_id="Drafts", name="Drafts", role="drafts")
        f_a = Folder(account_id=acc1.id, remote_id="FolderA", name="FolderA", role="other")
        f_b = Folder(account_id=acc1.id, remote_id="FolderB", name="FolderB", role="other")
        f_empty = Folder(account_id=acc1.id, remote_id="EmptyFolder", name="EmptyFolder", role="other")

        # Account 2 folder: Inbox
        f2_inbox = Folder(account_id=acc2.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add_all([f_inbox, f_drafts, f_a, f_b, f_empty, f2_inbox])
        session.flush()

        # Message 1 in FolderA
        m1 = Message(account_id=acc1.id, remote_id="m1", subject="Msg1", from_address="a@b.c", sort_time=datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc), is_read=False)
        # Message 2 in FolderB
        m2 = Message(account_id=acc1.id, remote_id="m2", subject="Msg2", from_address="a@b.c", sort_time=datetime(2026, 10, 21, 11, 0, tzinfo=timezone.utc), is_read=False)
        # Message 3 in BOTH Inbox and FolderA (simulating multi-label like Gmail)
        m3 = Message(account_id=acc1.id, remote_id="m3", subject="Msg3", from_address="a@b.c", sort_time=datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc), is_read=False)
        session.add_all([m1, m2, m3])
        session.flush()

        loc1 = MessageLocation(message_id=m1.id, folder_id=f_a.id, uid=1)
        loc2 = MessageLocation(message_id=m2.id, folder_id=f_b.id, uid=2)
        loc3_inbox = MessageLocation(message_id=m3.id, folder_id=f_inbox.id, uid=3)
        loc3_a = MessageLocation(message_id=m3.id, folder_id=f_a.id, uid=4)
        session.add_all([loc1, loc2, loc3_inbox, loc3_a])
        session.commit()

        # 1. AC-004: Query by specific folder_id f_a.id
        page_a = unified_inbox(session, folder_id=f_a.id)
        m_ids_a = [item.id for item in page_a.items]
        # Should contain m3 and m1, but NOT m2 (which is in FolderB)
        assert set(m_ids_a) == {m1.id, m3.id}

        # Query by specific folder_id f_b.id
        page_b = unified_inbox(session, folder_id=f_b.id)
        assert [item.id for item in page_b.items] == [m2.id]

        # Query empty folder: returns empty list without falling back to inbox
        page_empty = unified_inbox(session, folder_id=f_empty.id)
        assert len(page_empty.items) == 0

        # Query unknown folder_id raises LookupError
        with pytest.raises(LookupError):
            unified_inbox(session, folder_id=uuid.uuid4())

        # Cross-account mismatch: f_a does not belong to acc2
        with pytest.raises(LookupError):
            unified_inbox(session, account_ids=[acc2.id], folder_id=f_a.id)

        # 2. AC-005: Multi-location message deduplication across roles/folders
        # Querying with both f_inbox and f_a folder_ids (e.g. across folders)
        # m3 has locations in both f_inbox and f_a, but must only appear ONCE
        from mail_core.mail.application.queries import list_messages_keyset
        page_multi = list_messages_keyset(session, folder_ids=[f_inbox.id, f_a.id])
        item_ids = [item.id for item in page_multi.items]
        assert len(item_ids) == len(set(item_ids)), "Duplicate messages returned for multi-location message"
        assert item_ids.count(m3.id) == 1

        # 3. AC-007: mark_all_messages_read with specific folder_id only affects that folder
        batch = mark_all_messages_read(session, account_id=acc1.id, folder_id=f_b.id)
        session.commit()
        assert batch.count == 1
        assert batch.last_message_id is not None
        # m2 (in FolderB) is now read
        assert session.get(Message, m2.id).is_read is True
        # m1 (in FolderA) remains unread
        assert session.get(Message, m1.id).is_read is False


# --- AC-002: list_folder_stats_for_account 暴露 parent_remote_id ---


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_folder_stats_exposes_parent_remote_id():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"tree-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()

        f_parent = Folder(account_id=acc.id, remote_id="Parent", name="Parent", role="other")
        f_child = Folder(account_id=acc.id, remote_id="Parent/Child", name="Child", role="other", parent_remote_id="Parent")
        session.add_all([f_parent, f_child])
        session.commit()

        stats = list_folder_stats_for_account(session, acc.id)
        by_name = {s["name"]: s for s in stats}
        assert by_name["Parent"]["parent_remote_id"] is None
        assert by_name["Child"]["parent_remote_id"] == "Parent"
