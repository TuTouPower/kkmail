"""Test recompute_folder_stats protects initial creation against race conditions (SEC-06)."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from sqlalchemy.exc import IntegrityError

from mail_core.mail.storage.folder_stats import recompute_folder_stats
from mail_core.mail.storage.models import FolderStats


def test_recompute_folder_stats_handles_race_integrity_error():
    folder_id = uuid.uuid4()
    session = MagicMock()

    # Query returns (5, 2)
    session.execute.return_value.one.return_value = (5, 2)

    existing_stats = FolderStats(folder_id=folder_id, total_count=0, unread_count=0)

    # First session.get returns None (simulating race condition: row didn't exist when checked)
    # Second session.get after IntegrityError returns the row inserted by concurrent worker
    session.get.side_effect = [None, existing_stats]

    # session.begin_nested() context manager raises IntegrityError on flush
    nested_cm = MagicMock()
    nested_cm.__enter__.return_value = nested_cm
    nested_cm.__exit__.return_value = False
    session.begin_nested.return_value = nested_cm
    session.flush.side_effect = IntegrityError("duplicate key", params=None, orig=Exception())

    res = recompute_folder_stats(session, folder_id)

    assert res is existing_stats
    assert res.total_count == 5
    assert res.unread_count == 2
