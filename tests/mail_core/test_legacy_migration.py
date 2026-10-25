from __future__ import annotations

import hashlib
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import (
    Account,
    Folder,
    Message,
    MessageArchiveState,
    MessageBody,
    MessageLocation,
)
from scripts import migrate_from_legacy_db

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _legacy_source(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE retained_normal_mail_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL,
            provider_message_id TEXT NOT NULL,
            id_mode TEXT NOT NULL DEFAULT '',
            subject TEXT,
            sender TEXT,
            recipients TEXT,
            cc TEXT,
            received_at TEXT,
            body TEXT,
            body_type TEXT DEFAULT 'text',
            is_read INTEGER NOT NULL DEFAULT 0,
            has_attachments INTEGER NOT NULL DEFAULT 0,
            body_preview TEXT
        )
        """
    )
    conn.executemany(
        """
        INSERT INTO retained_normal_mail_messages (
            id, account_id, provider_message_id, id_mode, subject, sender,
            recipients, cc, received_at, body, body_type, is_read,
            has_attachments, body_preview
        ) VALUES (?, 7, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
        """,
        [
            (
                17,
                "42",
                "uid",
                None,
                None,
                "Bob <bob@example.net>, Carol <carol@example.org>",
                "Diane <diane@example.com>",
                "Wed, 21 Oct 2026 10:00:00 +0800",
                "<div>stored as plain text</div>",
                "text",
                None,
            ),
            (
                18,
                "graph-message-18",
                "graph",
                "无主题",
                "未知发件人",
                "Eve <eve@example.net>",
                "",
                "2026-10-20T12:30:00Z",
                "<div>stored as HTML</div>",
                "html",
                "Provider snippet",
            ),
            (
                19,
                "43",
                "sequence",
                "Sequence",
                "Seq <seq@example.net>",
                "",
                "",
                "2026-10-20T12:30:00Z",
                "Sequence body",
                "text",
                "",
            ),
            (
                20,
                "44",
                "uid",
                "Invalid date",
                "Sender <sender@example.net>",
                "",
                "",
                "not-a-date",
                "UID body",
                "text",
                "",
            ),
            (
                21,
                "",
                "uid",
                "Missing provider id",
                "sender@example.net",
                "",
                "",
                "2026-10-20T12:30:00Z",
                "Keep without remote identity",
                "text",
                "",
            ),
            (
                22,
                "not-a-uid",
                "uid",
                "Invalid UID",
                "Sender <sender@example.net>",
                "",
                "",
                "",
                "UID unknown",
                "text",
                "",
            ),
            (
                23,
                "graph-message-23",
                "graph",
                "Naive date",
                "Sender <sender@example.net>",
                "",
                "",
                "2026-10-20T12:30:00",
                "Naive date body",
                "text",
                "",
            ),
            (
                24,
                "unknown-message-24",
                "unknown",
                "Unknown mode",
                "Sender <sender@example.net>",
                "",
                "",
                "2026-10-20T12:30:00Z",
                "Unknown mode body",
                "text",
                "",
            ),
            (
                25,
                "graph-message-25",
                "graph",
                "Unknown body type",
                "Sender <sender@example.net>",
                "",
                "",
                "2026-10-20T12:30:00Z",
                "<div>keep literal, never render as HTML</div>",
                None,
                "",
            ),
            (
                26,
                "9223372036854775807",
                "uid",
                "Maximum UID",
                "Sender <sender@example.net>",
                "",
                "",
                "",
                "Maximum UID body",
                "text",
                "",
            ),
            (
                27,
                "9223372036854775808",
                "uid",
                "Out-of-range UID",
                "Sender <sender@example.net>",
                "",
                "",
                "",
                "Out-of-range UID body",
                "text",
                "",
            ),
            (
                28,
                "imap-message-28",
                "imap",
                "IMAP date provenance unknown",
                "Sender <sender@example.net>",
                "",
                "",
                "2026-10-20T12:30:00Z",
                "IMAP body",
                "text",
                "",
            ),
            (
                29,
                "empty-mode-message-29",
                "",
                "Empty mode",
                "Sender <sender@example.net>",
                "",
                "",
                "2026-10-20T12:30:00Z",
                "Empty mode body",
                "text",
                "",
            ),
            (
                30,
                "graph-message-30",
                "graph",
                "Missing Graph date",
                "Sender <sender@example.net>",
                "",
                "",
                None,
                "Missing date body",
                "text",
                "",
            ),
            (
                31,
                "graph-message-31",
                "graph",
                "Invalid Graph date",
                "Sender <sender@example.net>",
                "",
                "",
                "not-a-date",
                "Invalid date body",
                "text",
                "",
            ),
            (
                32,
                "0",
                "uid",
                "Zero UID",
                "Sender <sender@example.net>",
                "",
                "",
                None,
                "Zero UID body",
                "text",
                "",
            ),
            (
                33,
                "-1",
                "uid",
                "Negative UID",
                "Sender <sender@example.net>",
                "",
                "",
                None,
                "Negative UID body",
                "text",
                "",
            ),
            (
                34,
                "",
                "graph",
                "Graph empty ID and date",
                "Sender <sender@example.net>",
                "",
                "",
                None,
                "Graph empty ID body",
                "text",
                "",
            ),
            (
                35,
                "   ",
                "graph",
                "Graph whitespace ID without date",
                "Sender <sender@example.net>",
                "",
                "",
                None,
                "Graph whitespace ID body",
                "text",
                "",
            ),
            (
                36,
                "",
                "graph",
                "Graph empty ID with date",
                "Sender <sender@example.net>",
                "",
                "",
                "2026-10-20T12:30:00Z",
                "Graph empty ID and valid date body",
                "text",
                "",
            ),
            (
                37,
                "45",
                "uid",
                "",
                "",
                "",
                "",
                None,
                "Empty subject and sender body",
                "text",
                "",
            ),
            (
                38,
                "9" * 5000,
                "uid",
                "Oversized decimal UID",
                "Sender <sender@example.net>",
                "",
                "",
                None,
                "Oversized UID body",
                "text",
                "",
            ),
        ],
    )
    conn.commit()
    conn.close()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_importer_preserves_legacy_mail_fields_without_mutating_sqlite_source():
    source = Path(__file__).resolve().parents[2] / ".scratch" / f"legacy-import-{uuid.uuid4().hex}.sqlite"
    source_hash_before = _legacy_source(source)
    readonly = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    readonly.row_factory = sqlite3.Row

    Session = get_session_factory()
    account_id = None
    source_hash_after = ""
    try:
        with Session() as session:
            account = Account(
                email=f"legacy-import-{uuid.uuid4().hex[:8]}@example.com",
                provider="imap",
                credential_ref=f"legacy-import-{uuid.uuid4().hex[:8]}",
            )
            session.add(account)
            session.flush()
            folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
            session.add(folder)
            session.commit()
            account_id = account.id

            report = migrate_from_legacy_db.migrate_retained_messages(
                session,
                readonly.cursor(),
                account_id_map={7: account.id},
                folder_id_map={account.id: folder.id},
            )
            session.commit()

            assert report.migrated == 22
            assert report.imported_without_remote_id == 17
            assert report.skipped_existing == 0
            assert report.flag_state_unavailable == 22

            all_messages = list(session.scalars(select(Message).where(Message.account_id == account.id)))
            assert len(all_messages) == 22
            messages = {
                message.remote_id: message
                for message in all_messages
                if message.remote_id is not None
            }
            assert len(messages) == 5
            assert set(messages) == {
                "graph-message-18",
                "graph-message-23",
                "graph-message-25",
                "graph-message-30",
                "graph-message-31",
            }
            assert all(message.remote_id == key for key, message in messages.items())

            missing_fields = session.get(
                Message,
                uuid.uuid5(uuid.NAMESPACE_URL, f"kkmail:legacy-retained:{account.id}:17"),
            )
            assert missing_fields is not None and missing_fields.remote_id is None
            assert missing_fields.subject == ""
            assert missing_fields.from_address == ""
            assert missing_fields.to_addresses == ["bob@example.net", "carol@example.org"]
            assert missing_fields.cc_addresses == ["diane@example.com"]
            assert missing_fields.sort_time is None
            assert missing_fields.snippet is None

            literal_values = messages["graph-message-18"]
            assert literal_values.subject == "无主题"
            assert literal_values.from_address == ""
            assert literal_values.from_name == "未知发件人"
            assert literal_values.snippet == "Provider snippet"
            assert literal_values.sort_time == datetime(2026, 10, 20, 12, 30, tzinfo=timezone.utc)

            sequence = session.get(
                Message,
                uuid.uuid5(uuid.NAMESPACE_URL, f"kkmail:legacy-retained:{account.id}:19"),
            )
            assert sequence is not None and sequence.remote_id is None
            assert sequence.sort_time is None
            sequence_location = session.scalar(
                select(MessageLocation).where(MessageLocation.message_id == sequence.id)
            )
            assert sequence_location is not None and sequence_location.uid is None

            valid_uid = session.get(
                Message,
                uuid.uuid5(uuid.NAMESPACE_URL, f"kkmail:legacy-retained:{account.id}:20"),
            )
            assert valid_uid is not None and valid_uid.remote_id is None
            assert valid_uid.sort_time is None
            valid_uid_location = session.scalar(
                select(MessageLocation).where(MessageLocation.message_id == valid_uid.id)
            )
            assert valid_uid_location is not None and valid_uid_location.uid == 44

            invalid_uid = session.get(
                Message,
                uuid.uuid5(uuid.NAMESPACE_URL, f"kkmail:legacy-retained:{account.id}:22"),
            )
            assert invalid_uid is not None and invalid_uid.remote_id is None
            invalid_uid_location = session.scalar(
                select(MessageLocation).where(MessageLocation.message_id == invalid_uid.id)
            )
            assert invalid_uid_location is not None and invalid_uid_location.uid is None

            maximum_uid = session.get(
                Message,
                uuid.uuid5(uuid.NAMESPACE_URL, f"kkmail:legacy-retained:{account.id}:26"),
            )
            assert maximum_uid is not None and maximum_uid.remote_id is None
            maximum_uid_location = session.scalar(
                select(MessageLocation).where(MessageLocation.message_id == maximum_uid.id)
            )
            assert maximum_uid_location is not None
            assert maximum_uid_location.uid == 9223372036854775807

            out_of_range_uid = session.get(
                Message,
                uuid.uuid5(uuid.NAMESPACE_URL, f"kkmail:legacy-retained:{account.id}:27"),
            )
            assert out_of_range_uid is not None and out_of_range_uid.remote_id is None
            out_of_range_uid_location = session.scalar(
                select(MessageLocation).where(MessageLocation.message_id == out_of_range_uid.id)
            )
            assert out_of_range_uid_location is not None
            assert out_of_range_uid_location.uid is None

            invalid_local_ids = (28, 29, 32, 33, 34, 35, 38)
            for legacy_id in invalid_local_ids:
                local_only_message = session.get(
                    Message,
                    uuid.uuid5(uuid.NAMESPACE_URL, f"kkmail:legacy-retained:{account.id}:{legacy_id}"),
                )
                assert local_only_message is not None
                assert local_only_message.remote_id is None
                assert local_only_message.sort_time is None
                local_only_location = session.scalar(
                    select(MessageLocation).where(
                        MessageLocation.message_id == local_only_message.id
                    )
                )
                assert local_only_location is not None and local_only_location.uid is None

            missing_graph_time = messages["graph-message-30"]
            assert missing_graph_time.remote_id == "graph-message-30"
            assert missing_graph_time.sort_time is None
            missing_graph_location = session.scalar(
                select(MessageLocation).where(
                    MessageLocation.message_id == missing_graph_time.id
                )
            )
            assert missing_graph_location is not None and missing_graph_location.uid is None
            invalid_graph_time = messages["graph-message-31"]
            assert invalid_graph_time.remote_id == "graph-message-31"
            assert invalid_graph_time.sort_time is None
            invalid_graph_location = session.scalar(
                select(MessageLocation).where(
                    MessageLocation.message_id == invalid_graph_time.id
                )
            )
            assert invalid_graph_location is not None and invalid_graph_location.uid is None

            graph_empty_id_with_date = session.get(
                Message,
                uuid.uuid5(uuid.NAMESPACE_URL, f"kkmail:legacy-retained:{account.id}:36"),
            )
            assert graph_empty_id_with_date is not None
            assert graph_empty_id_with_date.remote_id is None
            assert graph_empty_id_with_date.sort_time == datetime(
                2026, 10, 20, 12, 30, tzinfo=timezone.utc
            )
            graph_empty_id_location = session.scalar(
                select(MessageLocation).where(
                    MessageLocation.message_id == graph_empty_id_with_date.id
                )
            )
            assert graph_empty_id_location is not None and graph_empty_id_location.uid is None

            empty_subject_sender = session.get(
                Message,
                uuid.uuid5(uuid.NAMESPACE_URL, f"kkmail:legacy-retained:{account.id}:37"),
            )
            assert empty_subject_sender is not None
            assert empty_subject_sender.subject == ""
            assert empty_subject_sender.from_address == ""
            assert empty_subject_sender.from_name is None
            assert empty_subject_sender.remote_id is None
            assert empty_subject_sender.sort_time is None
            empty_subject_sender_location = session.scalar(
                select(MessageLocation).where(
                    MessageLocation.message_id == empty_subject_sender.id
                )
            )
            assert empty_subject_sender_location is not None
            assert empty_subject_sender_location.uid == 45

            graph_without_timezone = messages["graph-message-23"]
            assert graph_without_timezone.sort_time is None
            graph_without_timezone_location = session.scalar(
                select(MessageLocation).where(
                    MessageLocation.message_id == graph_without_timezone.id
                )
            )
            assert graph_without_timezone_location is not None
            assert graph_without_timezone_location.uid is None
            unknown_mode = session.get(
                Message,
                uuid.uuid5(uuid.NAMESPACE_URL, f"kkmail:legacy-retained:{account.id}:24"),
            )
            assert unknown_mode is not None and unknown_mode.remote_id is None
            assert unknown_mode.sort_time is None
            assert messages["graph-message-25"].sort_time == datetime(
                2026, 10, 20, 12, 30, tzinfo=timezone.utc
            )
            missing_provider_id = session.get(
                Message,
                uuid.uuid5(uuid.NAMESPACE_URL, f"kkmail:legacy-retained:{account.id}:21"),
            )
            assert missing_provider_id is not None and missing_provider_id.remote_id is None
            assert missing_provider_id.subject == "Missing provider id"

            plain_body = session.get(MessageBody, missing_fields.id)
            html_body = session.get(MessageBody, literal_values.id)
            unknown_body = session.get(MessageBody, messages["graph-message-25"].id)
            assert plain_body is not None
            assert plain_body.text_plain == "<div>stored as plain text</div>"
            assert plain_body.text_html is None
            assert html_body is not None
            assert html_body.text_html == "<div>stored as HTML</div>"
            assert html_body.text_plain is None
            assert unknown_body is not None
            assert unknown_body.text_plain == "<div>keep literal, never render as HTML</div>"
            assert unknown_body.text_html is None

            assert session.get(MessageArchiveState, missing_fields.id) is None
            assert session.get(MessageArchiveState, literal_values.id) is None

            session.query(Message).filter_by(id=missing_fields.id).update({"subject": "already imported"})
            session.commit()

            again = migrate_from_legacy_db.migrate_retained_messages(
                session,
                readonly.cursor(),
                account_id_map={7: account.id},
                folder_id_map={account.id: folder.id},
            )
            session.commit()
            assert again.migrated == 0
            assert again.imported_without_remote_id == 0
            assert again.skipped_existing == 22
            assert again.flag_state_unavailable == 0
            assert session.get(Message, missing_fields.id).subject == "already imported"
            assert missing_fields.is_read is False
            assert missing_fields.has_attachments is False
            assert missing_fields.is_flagged is None
        source_hash_after = hashlib.sha256(source.read_bytes()).hexdigest()
    finally:
        readonly.close()
        if account_id is not None:
            with Session() as session:
                account = session.get(Account, account_id)
                if account is not None:
                    session.delete(account)
                    session.commit()
        source.unlink(missing_ok=True)

    assert source_hash_after == source_hash_before


def test_importer_migrates_all_retained_messages_not_just_recent_200():
    source = Path(__file__).resolve().parents[2] / ".scratch" / f"legacy-import-all-{uuid.uuid4().hex}.sqlite"
    _legacy_source(source)
    sqlite_conn = sqlite3.connect(source)
    sqlite_conn.executemany(
        """
        INSERT INTO retained_normal_mail_messages (
            id, account_id, provider_message_id, id_mode, subject, sender,
            recipients, cc, received_at, body, body_type, is_read,
            has_attachments, body_preview
        ) VALUES (?, 7, ?, 'graph', ?, 'Sender <sender@example.com>', '', '',
                  '2026-10-20T12:30:00Z', 'Body', 'text', 0, 0, 'Preview')
        """,
        [(1000 + i, f"extra-{i}", f"Extra {i}") for i in range(205)],
    )
    sqlite_conn.commit()
    sqlite_conn.close()
    readonly = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    readonly.row_factory = sqlite3.Row
    Session = get_session_factory()
    account_id = None
    try:
        with Session() as session:
            account = Account(
                email=f"legacy-all-{uuid.uuid4().hex[:8]}@example.com",
                provider="graph",
                credential_ref=f"legacy-all-{uuid.uuid4().hex[:8]}",
            )
            session.add(account)
            session.flush()
            folder = Folder(account_id=account.id, remote_id="INBOX", name="INBOX", role="inbox")
            session.add(folder)
            session.commit()
            account_id = account.id

            report = migrate_from_legacy_db.migrate_retained_messages(
                session,
                readonly.cursor(),
                account_id_map={7: account.id},
                folder_id_map={account.id: folder.id},
            )
            session.commit()

            assert report.migrated == 227
            assert report.legacy_total == 227
            assert session.query(Message).filter_by(account_id=account.id).count() == 227
    finally:
        readonly.close()
        if account_id is not None:
            with Session() as session:
                account = session.get(Account, account_id)
                if account is not None:
                    session.delete(account)
                    session.commit()
        source.unlink(missing_ok=True)
