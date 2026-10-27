"""A178: is_read / has_attachments must use the same flag parsing as is_flagged."""

from __future__ import annotations

import sqlite3
import uuid

import pytest

from mail_core.mail.storage.models import Message
from scripts.migrate_from_legacy_db import migrate_retained_messages


class Session:
    def __init__(self):
        self.added = []

    def get(self, _model, _message_id):
        return None

    def add(self, value):
        self.added.append(value)

    def flush(self):
        pass


def _migrate_one(*, is_read, has_attachments):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE retained_normal_mail_messages (
            id INTEGER PRIMARY KEY,
            account_id INTEGER NOT NULL,
            provider_message_id TEXT,
            id_mode TEXT,
            subject TEXT,
            sender TEXT,
            recipients TEXT,
            cc TEXT,
            received_at TEXT,
            body TEXT,
            body_type TEXT,
            is_read TEXT,
            has_attachments TEXT,
            body_preview TEXT
        )
        """
    )
    connection.execute(
        """INSERT INTO retained_normal_mail_messages (
                id, account_id, provider_message_id, id_mode, subject, sender,
                recipients, cc, received_at, body, body_type, is_read,
                has_attachments, body_preview
            ) VALUES (1, 7, 'local-only', 'unknown', 'Subject', 'Sender <sender@example.com>',
                      '', '', NULL, 'Body', 'text', ?, ?, '')""",
        (is_read, has_attachments),
    )
    session = Session()
    account_id = uuid.uuid4()
    report = migrate_retained_messages(
        session,
        connection.cursor(),
        account_id_map={7: account_id},
        folder_id_map={account_id: uuid.uuid4()},
    )
    connection.close()
    message = next(value for value in session.added if isinstance(value, Message))
    return report, message


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("false", False), ("0", False), ("no", False), ("true", True), ("1", True), ("yes", True)],
)
def test_string_flag_values_parse_like_is_flagged(raw, expected):
    _report, message = _migrate_one(is_read=raw, has_attachments=raw)

    assert message.is_read is expected
    assert message.has_attachments is expected


def test_unavailable_flag_values_default_false_and_are_counted_separately():
    report, message = _migrate_one(is_read=None, has_attachments="not-a-flag")

    assert message.is_read is False
    assert message.has_attachments is False
    assert report.read_state_unavailable == 1
    assert report.attachment_state_unavailable == 1


def test_available_flag_values_are_not_counted_as_unavailable():
    report, _message = _migrate_one(is_read="true", has_attachments="0")

    assert report.read_state_unavailable == 0
    assert report.attachment_state_unavailable == 0
