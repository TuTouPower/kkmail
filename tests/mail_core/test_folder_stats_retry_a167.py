"""A167: recompute_folder_stats must close the missing-row race.

When the initial INSERT lost the race (IntegrityError), the old code
re-fetched the row once and, if that re-fetch still returned None (winner
rolled back, row deleted in between), silently fell through and crashed
on ``stats.total_count`` with AttributeError — or worse, proceeded with a
phantom row. The recovery now retries a bounded number of times and
raises a clear error if the row never materialises.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy.exc import IntegrityError

from mail_core.mail.storage.folder_stats import recompute_folder_stats
from mail_core.mail.storage.models import FolderStats


class _Result:
    def __init__(self, row):
        self._row = row

    def one(self):
        return self._row


class _FakeSession:
    """Scripted session: get() pops from `get_results`; flush() raises
    IntegrityError while `fail_flushes` remains."""

    def __init__(self, get_results, fail_flushes=0, counts=(7, 3, 0)):
        self._get_results = list(get_results)
        self._fail_flushes = fail_flushes
        self._counts = counts
        self.added: list = []
        self.get_calls = 0

    def get(self, _cls, _pk, with_for_update=False):
        self.get_calls += 1
        if self._get_results:
            return self._get_results.pop(0)
        return None

    @contextmanager
    def begin_nested(self):
        yield

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        if self._fail_flushes > 0:
            self._fail_flushes -= 1
            raise IntegrityError("INSERT", {}, Exception("duplicate key"))

    def execute(self, _stmt):
        return _Result(self._counts)


def test_missing_row_that_never_appears_raises_instead_of_attribute_error():
    session = _FakeSession(get_results=[None, None, None, None], fail_flushes=99)
    with pytest.raises(RuntimeError, match="folder_stats"):
        recompute_folder_stats(session, uuid.uuid4())
    # Bounded: initial get + a limited number of retries, not an infinite loop.
    assert session.get_calls <= 5


def test_race_loser_recovers_when_row_appears_on_refetch():
    folder_id = uuid.uuid4()
    winner = FolderStats(folder_id=folder_id)
    session = _FakeSession(get_results=[None, winner], fail_flushes=1)
    stats = recompute_folder_stats(session, folder_id)
    assert stats is winner
    assert stats.total_count == 7
    assert stats.unread_count == 3


def test_insert_path_still_creates_and_populates_stats():
    folder_id = uuid.uuid4()
    session = _FakeSession(get_results=[None], fail_flushes=0)
    stats = recompute_folder_stats(session, folder_id)
    assert isinstance(stats, FolderStats)
    assert stats.folder_id == folder_id
    assert stats.total_count == 7
    assert stats.unread_count == 3
