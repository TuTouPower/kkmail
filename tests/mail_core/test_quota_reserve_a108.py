"""A108: reserve_quota must distinguish "no reservation needed" from
"hard quota exceeded", and must not walk the whole blob directory while
holding the hard-quota advisory lock.

Old contract: both cases returned None, and dir_size_bytes(root) ran
*inside* the advisory lock, so every reservation held a global lock for
the duration of a full filesystem walk.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import mail_core.blobs.quota as quota_mod
from mail_core.blobs.quota import QuotaExceededError, reserve_quota


class _FakeSession:
    """Minimal session double speaking the reserve_quota protocol.

    `events` records the order of lock / reserved-read / insert steps.
    """

    def __init__(self, *, reserved: int = 0, events: list | None = None):
        self._reserved = reserved
        self.events = events if events is not None else []
        self.added: list = []

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def execute(self, _stmt, _params=None):
        self.events.append("lock")
        return None

    def scalar(self, _stmt):
        self.events.append("reserved")
        return self._reserved

    def add(self, obj):
        self.events.append("insert")
        self.added.append(obj)

    def flush(self):
        pass


@pytest.fixture(autouse=True)
def _clear_cache():
    quota_mod._clear_dir_size_cache()
    yield
    quota_mod._clear_dir_size_cache()


def test_exceeded_hard_quota_raises_distinct_error(tmp_path):
    session = _FakeSession(reserved=0)
    with pytest.raises(QuotaExceededError):
        reserve_quota(
            session,
            root=tmp_path,
            needed_bytes=101,
            worker_id="w1",
            hard_limit_bytes=100,
        )
    assert session.added == []


def test_no_reservation_needed_returns_none_without_lock_or_insert(tmp_path):
    session = _FakeSession()
    assert (
        reserve_quota(session, root=tmp_path, needed_bytes=0, worker_id="w1", hard_limit_bytes=100)
        is None
    )
    assert session.events == []
    assert session.added == []


def test_successful_reservation_returns_id_and_records_bytes(tmp_path):
    session = _FakeSession(reserved=10)
    res_id = reserve_quota(
        session,
        root=tmp_path,
        needed_bytes=50,
        worker_id="w1",
        hard_limit_bytes=100,
    )
    assert isinstance(res_id, uuid.UUID)
    assert len(session.added) == 1
    assert session.added[0].reserved_bytes == 50
    assert session.added[0].id == res_id


def test_directory_walk_happens_before_the_lock(tmp_path, monkeypatch):
    events: list = []

    def fake_walk(_root):
        events.append("walk")
        return 0

    monkeypatch.setattr(quota_mod, "dir_size_bytes", fake_walk)
    session = _FakeSession(reserved=0, events=events)
    reserve_quota(session, root=tmp_path, needed_bytes=10, worker_id="w1", hard_limit_bytes=100)
    # Short critical section: walk (cached snapshot) precedes the lock; the
    # lock only covers reading active reservations, deciding, and inserting.
    assert events == ["walk", "lock", "reserved", "insert"]


def test_dir_size_cache_avoids_repeated_walks(tmp_path, monkeypatch):
    walks: list = []
    monkeypatch.setattr(quota_mod, "dir_size_bytes", lambda root: walks.append(root) or 42)
    assert quota_mod.dir_size_bytes_cached(tmp_path) == 42
    assert quota_mod.dir_size_bytes_cached(tmp_path) == 42
    assert len(walks) == 1
