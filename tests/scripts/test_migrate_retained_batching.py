"""A158: retained-message migration must commit/expunge in bounded batches."""

from __future__ import annotations

import sqlite3
import uuid

import pytest

from mail_core.mail.storage.models import Message
from scripts.migrate_from_legacy_db import migrate_retained_messages


class BatchSession:
    def __init__(self, existing_ids=()):
        self.added = []
        self.commits = 0
        self.expunges = 0
        self._existing_ids = set(existing_ids)

    def get(self, _model, message_id):
        return object() if message_id in self._existing_ids else None

    def add(self, value):
        self.added.append(value)

    def flush(self):
        pass

    def commit(self):
        self.commits += 1

    def expunge_all(self):
        self.expunges += 1


def _source(row_count):
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
            is_read INTEGER,
            has_attachments INTEGER,
            body_preview TEXT
        )
        """
    )
    connection.executemany(
        """INSERT INTO retained_normal_mail_messages (
                id, account_id, provider_message_id, id_mode, subject, sender,
                recipients, cc, received_at, body, body_type, is_read,
                has_attachments, body_preview
            ) VALUES (?, 7, 'local-only', 'unknown', 'Subject', 'Sender <sender@example.com>',
                      '', '', NULL, 'Body', 'text', 0, 0, '')""",
        [(i,) for i in range(1, row_count + 1)],
    )
    return connection


def _run(connection, session, *, batch_size):
    account_id = uuid.uuid4()
    return migrate_retained_messages(
        session,
        connection.cursor(),
        account_id_map={7: account_id},
        folder_id_map={account_id: uuid.uuid4()},
        batch_size=batch_size,
    )


def test_migration_commits_and_expunges_per_batch_with_cumulative_counts():
    connection = _source(5)
    session = BatchSession()

    report = _run(connection, session, batch_size=2)
    connection.close()

    assert report.migrated == 5
    assert report.legacy_total == 5
    # Batches of 2 and 2 are committed inside the migration; the final
    # partial batch is left for the caller's commit.
    assert session.commits == 2
    assert session.expunges == 2
    assert sum(1 for value in session.added if isinstance(value, Message)) == 5


def test_skipped_existing_rows_also_advance_the_batch():
    connection = _source(3)
    account_id = uuid.uuid4()
    existing_ids = {
        uuid.uuid5(uuid.NAMESPACE_URL, f"kkmail:legacy-retained:{account_id}:{i}")
        for i in (1, 2, 3)
    }
    session = BatchSession(existing_ids=existing_ids)

    report = migrate_retained_messages(
        session,
        connection.cursor(),
        account_id_map={7: account_id},
        folder_id_map={account_id: uuid.uuid4()},
        batch_size=2,
    )
    connection.close()

    assert report.migrated == 0
    assert report.skipped_existing == 3
    assert session.commits == 1
    assert session.expunges == 1


def test_batch_size_must_be_positive():
    connection = _source(1)
    session = BatchSession()

    with pytest.raises(ValueError, match="batch_size"):
        _run(connection, session, batch_size=0)
    connection.close()
