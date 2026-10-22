from __future__ import annotations

import email.utils
import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from mail_core.mail.storage.models import Account, Folder, Message, MessageSearch
from mail_core.providers.base import MetadataPage, RemoteMessageMeta
from mail_core.providers.imap import (
    _decode_header,
    _parse_from,
    _parse_message_meta_from_fetch,
)
from mail_core.sync.leases import acquire_lease
from mail_core.sync.metadata import apply_metadata_page


# --- AC-001: IMAP 返回裸 GBK 与 GB2312 报头解码 ---


def test_ac001_bare_gbk_and_gb2312_header_decode():
    # GBK-encoded bytes for "测试主题" (b"\xb2\xe2\xca\xd4\xd6\xf7\xcc\xe2")
    # GBK-encoded bytes for "张三" (b"\xd5\xc5\xc8\xfd")
    # GB2312-encoded bytes for "李四" (b"\xc0\xee\xc4\xc4")
    # GB2312-encoded bytes for "王五" (b"\xcd\xf5\xce\xe5")
    header_bytes = (
        b"Subject: \xb2\xe2\xca\xd4\xd6\xf7\xcc\xe2\r\n"
        b"From: \xd5\xc5\xc8\xfd <zhangsan@example.com>\r\n"
        b"To: \xc0\xee\xc4\xc4 <lisi@example.com>\r\n"
        b"Cc: \xcd\xf5\xce\xe5 <wangwu@example.com>\r\n"
        b"Date: Wed, 21 Oct 2026 10:00:00 +0800\r\n"
        b"Message-ID: <msg-ac001@example.com>\r\n"
        b"\r\n"
    )
    flags_blob = (b"1 (UID 1001 FLAGS (\\Seen))", header_bytes)
    meta = _parse_message_meta_from_fetch(
        flags_blob=flags_blob,
        uid_fallback=1001,
        folder_remote_id="INBOX",
        uidvalidity=42,
    )

    assert meta is not None
    assert meta.subject == "测试主题"
    assert meta.from_name == "张三"
    assert meta.from_address == "zhangsan@example.com"
    assert meta.to_addresses == ("lisi@example.com",)
    assert meta.cc_addresses == ("wangwu@example.com",)
    assert meta.internet_message_id == "<msg-ac001@example.com>"
    assert meta.sort_time == datetime(2026, 10, 21, 2, 0, 0, tzinfo=timezone.utc)
    assert meta.is_read is True
    assert meta.uid == 1001
    assert "\x1fINBOX\x1f1001" in meta.remote_id


# --- AC-002: ASCII、裸 UTF-8、RFC 2047、混合编码及折行报头 ---


def test_ac002_ascii_utf8_rfc2047_mixed_and_folding():
    # 1. ASCII
    ascii_hdr = b"Subject: Simple ASCII\r\nFrom: Alice <alice@example.com>\r\n\r\n"
    meta_ascii = _parse_message_meta_from_fetch((b"1 (UID 101)", ascii_hdr), 101, "INBOX", 1)
    assert meta_ascii.subject == "Simple ASCII"
    assert meta_ascii.from_name == "Alice"
    assert meta_ascii.from_address == "alice@example.com"

    # 2. Bare UTF-8
    utf8_hdr = (
        b"Subject: \xe6\xb5\x8b\xe8\xaf\x95\xe4\xb8\xbb\xe9\xa2\x98\r\n"
        b"From: \xe5\xbc\xa0\xe4\xb8\x89 <zhang@example.com>\r\n\r\n"
    )
    meta_utf8 = _parse_message_meta_from_fetch((b"2 (UID 102)", utf8_hdr), 102, "INBOX", 1)
    assert meta_utf8.subject == "测试主题"
    assert meta_utf8.from_name == "张三"
    assert meta_utf8.from_address == "zhang@example.com"

    # 3. RFC 2047 UTF-8 & GBK
    rfc_hdr = (
        b"Subject: =?utf-8?B?5rWL6K+V?= =?gbk?B?suLK1A==?=\r\n"
        b"From: =?utf-8?B?5byg5LiJ?= <zhang@example.com>\r\n\r\n"
    )
    meta_rfc = _parse_message_meta_from_fetch((b"3 (UID 103)", rfc_hdr), 103, "INBOX", 1)
    assert meta_rfc.subject == "测试测试"
    assert meta_rfc.from_name == "张三"

    # 4. Mixed RFC 2047 and Bare GBK
    mixed_hdr = (
        b"Subject: =?utf-8?B?5rWL6K+V?= \xb2\xe2\xca\xd4\r\n"
        b"From: \xd5\xc5\xc8\xfd <zhang@example.com>\r\n\r\n"
    )
    meta_mixed = _parse_message_meta_from_fetch((b"4 (UID 104)", mixed_hdr), 104, "INBOX", 1)
    assert meta_mixed.subject == "测试 测试"
    assert meta_mixed.from_name == "张三"

    # 5. Folded header
    folded_hdr = (
        b"Subject: Long Subject Line That\r\n"
        b" \xb2\xe2\xca\xd4 Is Folded\r\n"
        b"From: Alice\r\n"
        b" <alice@example.com>\r\n\r\n"
    )
    meta_folded = _parse_message_meta_from_fetch((b"5 (UID 105)", folded_hdr), 105, "INBOX", 1)
    assert "测试" in meta_folded.subject
    assert meta_folded.from_address == "alice@example.com"


# --- AC-003: 未知 charset 与损坏报头隔离 ---


def test_ac003_corrupted_header_isolated_fallback():
    # Corrupted Subject bytes b"\xff\xfe\xff", but From and To are valid bare GBK
    bad_hdr = (
        b"Subject: \xff\xfe\xff\r\n"
        b"From: \xd5\xc5\xc8\xfd <zhang@example.com>\r\n"
        b"To: =?unknown-custom-charset?B?dGVzdA==?= <dest@example.com>\r\n\r\n"
    )
    meta_bad = _parse_message_meta_from_fetch((b"6 (UID 106)", bad_hdr), 106, "INBOX", 1)
    assert meta_bad is not None
    # Corrupted subject uses lossy replacement without crashing
    assert "\ufffd" in meta_bad.subject
    # Other fields remain cleanly decoded
    assert meta_bad.from_name == "张三"
    assert meta_bad.from_address == "zhang@example.com"
    assert meta_bad.to_addresses == ("dest@example.com",)


# --- AC-004: 同一邮件重新获取元数据经 apply 更新旧记录与搜索索引 ---


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_ac004_metadata_refetch_updates_mojibake_and_search_index():
    from datetime import timedelta
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc = Account(email=f"gbk-{uuid.uuid4().hex[:8]}@example.com", provider="imap")
        session.add(acc)
        session.flush()
        folder = Folder(account_id=acc.id, remote_id="INBOX", name="INBOX", role="inbox")
        session.add(folder)
        session.flush()

        lease = acquire_lease(session, account_id=acc.id, owner_id="w1", ttl=timedelta(minutes=5))

        # 1. First sync: message recorded with corrupted/mojibake text (old behavior)
        remote_id = "1\x1fINBOX\x1f2001"
        page_old = MetadataPage(
            items=[
                RemoteMessageMeta(
                    remote_id=remote_id,
                    subject="",  # mojibake
                    from_address="sender@example.com",
                    from_name="",
                    sort_time=datetime(2026, 10, 21, 10, 0, tzinfo=timezone.utc),
                    is_read=False,
                    has_attachments=False,
                    uid=2001,
                )
            ],
            next_cursor={"uid_next": 2002, "uidvalidity": 1},
            exhausted=True,
        )
        res1 = apply_metadata_page(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=page_old,
        )
        session.commit()
        assert res1.upserted == 1

        msg = session.scalar(select(Message).where(Message.account_id == acc.id, Message.remote_id == remote_id))
        assert msg is not None
        mid = msg.id
        search_old = session.get(MessageSearch, mid)
        assert search_old is not None
        assert "" in search_old.subject

        # 2. Refetch raw header and re-apply corrected metadata
        corrected_meta = _parse_message_meta_from_fetch(
            flags_blob=(
                b"1 (UID 2001 FLAGS ())",
                b"Subject: \xb2\xe2\xca\xd4\xd6\xf7\xcc\xe2\r\n"
                b"From: \xd5\xc5\xc8\xfd <sender@example.com>\r\n\r\n",
            ),
            uid_fallback=2001,
            folder_remote_id="INBOX",
            uidvalidity=1,
        )
        assert corrected_meta is not None
        assert corrected_meta.subject == "测试主题"
        assert corrected_meta.from_name == "张三"

        page_fixed = MetadataPage(
            items=[corrected_meta],
            next_cursor={"uid_next": 2002, "uidvalidity": 1},
            exhausted=True,
        )
        res2 = apply_metadata_page(
            session,
            account_id=acc.id,
            folder_id=folder.id,
            fencing_token=lease.fencing_token,
            page=page_fixed,
        )
        session.commit()
        assert res2.upserted == 1

        # 3. Verify message ID identity is preserved, fields are updated, no duplicate messages
        all_msgs = session.scalars(select(Message).where(Message.account_id == acc.id)).all()
        assert len(all_msgs) == 1
        updated_msg = all_msgs[0]
        assert updated_msg.id == mid
        assert updated_msg.subject == "测试主题"
        assert updated_msg.from_name == "张三"

        search_updated = session.get(MessageSearch, mid)
        assert search_updated is not None
        assert search_updated.subject == "测试主题"
