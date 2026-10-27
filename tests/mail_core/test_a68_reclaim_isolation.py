"""A68: each reclaim sweep runs in its own session/transaction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mail_core.worker import main as worker_main


class _FakeSession:
    def __init__(self, registry):
        self.commits = 0
        self.rollbacks = 0
        registry.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _run_reclaim(monkeypatch, *, failing: str | None = None):
    registry: list[_FakeSession] = []

    def factory():
        return _FakeSession(registry)

    counts = {
        "stale": 2,
        "archive": 3,
        "published": 10,
        "jobs": 4,
        "converge": 7,
        "quota": 8,
        "resume": 9,
        "heartbeats": 5,
    }

    def make(name):
        def _fn(*_args, **_kwargs):
            if failing == name:
                raise RuntimeError(f"{name} boom")
            return counts[name]

        return MagicMock(side_effect=_fn)

    mocks = {name: make(name) for name in counts}
    with (
        patch("mail_core.db.session.get_session_factory", return_value=factory),
        patch("mail_core.sync.jobs.reclaim_stale_claims", mocks["stale"]),
        patch("mail_core.blobs.archive.reclaim_stale_archive_claims", mocks["archive"]),
        patch("mail_core.realtime.outbox.prune_published", mocks["published"]),
        patch("mail_core.sync.jobs.prune_completed_jobs", mocks["jobs"]),
        patch("mail_core.sync.execution.converge_orphaned_bindings", mocks["converge"]),
        patch("mail_core.blobs.quota.prune_expired_quota_reservations", mocks["quota"]),
        patch("mail_core.blobs.archive.maybe_resume_quota_paused_archives", mocks["resume"]),
        patch("mail_core.worker.heartbeat.cleanup_stale_heartbeats", mocks["heartbeats"]),
    ):
        total = worker_main._reclaim_once()
    return total, registry, mocks, counts


def test_each_sweep_uses_its_own_session_and_commit(monkeypatch):
    total, registry, mocks, _counts = _run_reclaim(monkeypatch)

    # Return keeps the historical counted subset: stale + archive + published
    # + jobs + heartbeats.
    assert total == 2 + 3 + 10 + 4 + 5
    assert len(registry) == 8
    assert all(session.commits == 1 for session in registry)
    assert all(session.rollbacks == 0 for session in registry)
    assert all(mock.call_count == 1 for mock in mocks.values())


def test_one_failing_sweep_does_not_block_or_roll_back_others(monkeypatch):
    total, registry, mocks, _counts = _run_reclaim(monkeypatch, failing="published")

    # prune_published contributed 0; every other sweep still ran and kept its
    # count (published sits mid-list, so jobs/converge/quota/resume/heartbeats
    # must not be skipped).
    assert total == 2 + 3 + 4 + 5
    assert all(mock.call_count == 1 for mock in mocks.values())
    assert len(registry) == 8
    failed_sessions = [s for s in registry if s.rollbacks == 1]
    committed_sessions = [s for s in registry if s.commits == 1]
    assert len(failed_sessions) == 1
    assert len(committed_sessions) == 7
