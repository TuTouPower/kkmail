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


def _migrate_one(*, flag_column=None, flag_value=None):
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    flag_ddl = f", {flag_column} TEXT" if flag_column else ""
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
            is_read INTEGER,
            has_attachments INTEGER,
            body_preview TEXT
        """ + flag_ddl + ")"
    )
    if flag_column:
        connection.execute(
            f"""INSERT INTO retained_normal_mail_messages (
                    id, account_id, provider_message_id, id_mode, subject, sender,
                    recipients, cc, received_at, body, body_type, is_read,
                    has_attachments, body_preview, {flag_column}
                ) VALUES (1, 7, 'local-only', 'unknown', 'Subject', 'Sender <sender@example.com>',
                          '', '', NULL, 'Body', 'text', 0, 0, '', ?)""",
            (flag_value,),
        )
    else:
        connection.execute(
            """INSERT INTO retained_normal_mail_messages (
                    id, account_id, provider_message_id, id_mode, subject, sender,
                    recipients, cc, received_at, body, body_type, is_read,
                    has_attachments, body_preview
                ) VALUES (1, 7, 'local-only', 'unknown', 'Subject', 'Sender <sender@example.com>',
                          '', '', NULL, 'Body', 'text', 0, 0, '')"""
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
    ("column", "value", "expected"),
    [("is_flagged", "1", True), ("is_flagged", "0", False), ("is_starred", "true", True)],
)
def test_migration_maps_available_legacy_flag_column(column, value, expected):
    report, message = _migrate_one(flag_column=column, flag_value=value)

    assert message.is_flagged is expected
    assert report.flag_state_unavailable == 0


def test_migration_reports_unavailable_legacy_flag_state():
    report, message = _migrate_one()

    assert message.is_flagged is None
    assert report.flag_state_unavailable == 1
