"""t061 AC-008..AC-014: all-folder STATUS patrol scheduler.

DB-backed tests follow the test_worker_scheduler pattern (skipped
without MAIL_CORE_DATABASE_URL); the pure comparison logic is tested
without a database.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.mail.domain.enums import JobStatus, JobType, SyncStatus
from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint, WorkerJob
from mail_core.providers.base import FolderStatus
from mail_core.sync.patrol import (
    PatrolConfig,
    changed_dimensions,
    schedule_folder_status_patrol,
)

pytestmark_db = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


# ---------------------------------------------------------------------------
# Pure comparison logic (no DB)
# ---------------------------------------------------------------------------


def test_changed_dimensions_compares_only_shared_values():
    base = FolderStatus(messages=3, uidnext=9, unseen=1, highestmodseq=77)
    same = FolderStatus(messages=3, uidnext=9, unseen=1, highestmodseq=77)
    assert changed_dimensions(base, same) == ()

    moved = FolderStatus(messages=4, uidnext=10, unseen=1, highestmodseq=78)
    assert set(changed_dimensions(base, moved)) == {"messages", "uidnext", "highestmodseq"}


def test_changed_dimensions_missing_uidnext_falls_back_to_counts():
    base = FolderStatus(messages=3, uidnext=None, unseen=1, highestmodseq=None)
    deleted = FolderStatus(messages=2, uidnext=None, unseen=1, highestmodseq=None)
    assert changed_dimensions(base, deleted) == ("messages",)
    read_elsewhere = FolderStatus(messages=3, uidnext=None, unseen=0, highestmodseq=None)
    assert changed_dimensions(base, read_elsewhere) == ("unseen",)
    # A dimension present only on one side never fires on its own.
    probe = FolderStatus(messages=3, uidnext=12, unseen=1, highestmodseq=None)
    assert changed_dimensions(base, probe) == ()


# ---------------------------------------------------------------------------
# DB-backed patrol behaviour
# ---------------------------------------------------------------------------


def _seed_folder(
    session,
    *,
    role: str = "sent",
    sync_status: str = SyncStatus.IDLE.value,
    sync_enabled: bool = True,
    provider: str = "stub",
    baseline: bool = True,
    last_status: dict | None = None,
    last_probe_epoch: float | None = None,
) -> tuple[Account, Folder]:
    acc = Account(
        id=uuid.uuid4(),
        email=f"patrol-{uuid.uuid4().hex[:8]}@example.com",
        provider=provider,
        credential_ref=f"ref-{uuid.uuid4().hex[:6]}",
        sync_enabled=sync_enabled,
        config={"folders": [{"remote_id": "INBOX", "name": "INBOX", "role": "inbox"}]},
    )
    session.add(acc)
    session.flush()
    folder = Folder(
        id=uuid.uuid4(),
        account_id=acc.id,
        remote_id=f"remote-{uuid.uuid4().hex[:6]}",
        name=role.title(),
        role=role,
        sync_status=sync_status,
    )
    session.add(folder)
    session.flush()
    cursor: dict = {}
    if last_status is not None:
        cursor["last_status"] = last_status
    if last_probe_epoch is not None:
        cursor["last_probe_at"] = last_probe_epoch
    cp = SyncCheckpoint(
        account_id=acc.id,
        folder_id=folder.id,
        cursor=cursor,
        full_scan_complete=baseline,
    )
    session.add(cp)
    session.flush()
    return acc, folder


def _cfg(**overrides) -> PatrolConfig:
    base = PatrolConfig(
        enabled=True,
        interval_s=1200.0,
        max_probes=200,
        max_unprobed_s=2400.0,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _delta_jobs(session, account_id, folder_id):
    return list(
        session.scalars(
            select(WorkerJob).where(
                WorkerJob.account_id == account_id,
                WorkerJob.dedupe_key == f"delta:{account_id}:{folder_id}",
            )
        ).all()
    )


class _FakeProbeProvider:
    """Provider double injected via provider_factory."""

    def __init__(self, status: FolderStatus | None, *, fail: bool = False):
        self._status = status
        self._fail = fail
        self.probed: list[str] = []

    def probe_folder_status(self, folder_remote_id: str):
        self.probed.append(folder_remote_id)
        if self._fail:
            raise RuntimeError("probe boom")
        return self._status


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_ac008_ac009_first_probe_records_baseline_without_enqueue():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    provider = _FakeProbeProvider(FolderStatus(messages=5, uidnext=6, unseen=2, highestmodseq=9))
    seeded: list[tuple[uuid.UUID, uuid.UUID, str]] = []
    with Session() as session:
        # AC-008 coverage spans every non-inbox role family (test f006).
        for role in ("sent", "drafts", "trash", "custom"):
            acc, folder = _seed_folder(session, role=role)
            seeded.append((acc.id, folder.id, folder.remote_id))
        session.commit()

    with Session() as session:
        result = schedule_folder_status_patrol(
            session,
            config=_cfg(),
            provider_factory=lambda account: provider,
            now=datetime.now(timezone.utc),
        )
        session.commit()
        assert result.probed == 4
        assert result.changed == 0
        assert set(provider.probed) == {remote for _a, _f, remote in seeded}
        for acc_id, folder_id, _remote in seeded:
            assert _delta_jobs(session, acc_id, folder_id) == []
            cp = session.get(
                SyncCheckpoint, {"account_id": acc_id, "folder_id": folder_id}
            )
            assert cp.cursor["last_status"]["messages"] == 5
            assert "last_probe_at" in cp.cursor


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_ac009_unchanged_probe_enqueues_nothing():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    status = FolderStatus(messages=5, uidnext=6, unseen=2, highestmodseq=9)
    provider = _FakeProbeProvider(status)
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc, folder = _seed_folder(
            session,
            last_status=status.to_dict(),
            last_probe_epoch=(now - timedelta(seconds=1300)).timestamp(),
        )
        acc_id, folder_id = acc.id, folder.id
        session.commit()

    with Session() as session:
        result = schedule_folder_status_patrol(
            session, config=_cfg(), provider_factory=lambda account: provider, now=now
        )
        session.commit()
        assert result.probed == 1
        assert result.changed == 0
        assert _delta_jobs(session, acc_id, folder_id) == []


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_ac010_changed_probe_enqueues_delta_and_updates_baseline():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    before = FolderStatus(messages=5, uidnext=6, unseen=2, highestmodseq=9)
    after = FolderStatus(messages=6, uidnext=7, unseen=3, highestmodseq=10)
    provider = _FakeProbeProvider(after)
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc, folder = _seed_folder(
            session,
            last_status=before.to_dict(),
            last_probe_epoch=(now - timedelta(seconds=1300)).timestamp(),
        )
        acc_id, folder_id = acc.id, folder.id
        session.commit()

    with Session() as session:
        result = schedule_folder_status_patrol(
            session, config=_cfg(), provider_factory=lambda account: provider, now=now
        )
        session.commit()
        assert result.changed == 1
        jobs = _delta_jobs(session, acc_id, folder_id)
        assert len(jobs) == 1
        assert jobs[0].job_type == JobType.SYNC_FOLDER_DELTA.value
        assert jobs[0].status == JobStatus.PENDING.value
        assert jobs[0].payload == {"folder_id": str(folder_id)}
        cp = session.get(SyncCheckpoint, {"account_id": acc_id, "folder_id": folder_id})
        assert cp.cursor["last_status"]["messages"] == 6


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_ac011_ac012_skips_paused_disabled_and_records_no_baseline():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    provider = _FakeProbeProvider(FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1))
    now = datetime.now(timezone.utc)
    old = (now - timedelta(seconds=1300)).timestamp()
    with Session() as session:
        acc_paused, f_paused = _seed_folder(session, sync_status=SyncStatus.PAUSED.value, last_probe_epoch=old)
        acc_disabled, f_disabled = _seed_folder(session, sync_enabled=False, last_probe_epoch=old)
        acc_nobase, f_nobase = _seed_folder(session, baseline=False, last_probe_epoch=old)
        session.commit()
        ids = {
            "paused": (acc_paused.id, f_paused.id),
            "disabled": (acc_disabled.id, f_disabled.id),
            "nobase": (acc_nobase.id, f_nobase.id),
        }

    with Session() as session:
        result = schedule_folder_status_patrol(
            session, config=_cfg(), provider_factory=lambda account: provider, now=now
        )
        session.commit()
        # Only the no-baseline folder is probed (record-only); paused and
        # disabled targets never reach the provider.
        assert result.probed == 1
        assert len(provider.probed) == 1
        for acc_id, folder_id in ids.values():
            assert _delta_jobs(session, acc_id, folder_id) == []
        cp = session.get(
            SyncCheckpoint, {"account_id": ids["nobase"][0], "folder_id": ids["nobase"][1]}
        )
        assert cp.cursor["last_status"]["messages"] == 1
        assert cp.full_scan_complete is False


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_ac013_rotation_respects_cap_and_oldest_first():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    provider = _FakeProbeProvider(FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1))
    now = datetime.now(timezone.utc)
    remote_ids: list[str] = []
    with Session() as session:
        for i in range(5):
            _acc, folder = _seed_folder(
                session,
                last_status={"messages": 1, "uidnext": 2, "unseen": 0, "highestmodseq": 1},
                # Oldest probe first: folder 0 probed longest ago.
                last_probe_epoch=(now - timedelta(seconds=5000 - i * 100)).timestamp(),
            )
            remote_ids.append(folder.remote_id)
        session.commit()

    with Session() as session:
        result = schedule_folder_status_patrol(
            session,
            config=_cfg(max_probes=2),
            provider_factory=lambda account: provider,
            now=now,
        )
        session.commit()
        assert result.probed == 2
        # Exactly the two least-recently probed folders were chosen —
        # reversing the sort order must fail this assertion.
        assert set(provider.probed) == {remote_ids[0], remote_ids[1]}

    # Second sweep at a later time probes the next-oldest pair; within a
    # bounded number of sweeps every folder is probed (AC-013 rotation).
    with Session() as session:
        result2 = schedule_folder_status_patrol(
            session,
            config=_cfg(max_probes=2),
            provider_factory=lambda account: provider,
            now=now + timedelta(seconds=60),
        )
        session.commit()
        assert result2.probed == 2
        assert set(provider.probed[2:]) == {remote_ids[2], remote_ids[3]}
    with Session() as session:
        result3 = schedule_folder_status_patrol(
            session,
            config=_cfg(max_probes=2),
            provider_factory=lambda account: provider,
            now=now + timedelta(seconds=120),
        )
        session.commit()
        assert result3.probed == 1
        assert provider.probed[-1] == remote_ids[4]
        # Full coverage across the three sweeps, no folder probed twice.
        assert sorted(provider.probed) == sorted(remote_ids)


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_ac014_probe_failure_isolated_per_folder():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    old = (now - timedelta(seconds=1300)).timestamp()
    status = FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)
    with Session() as session:
        acc_bad, f_bad = _seed_folder(session, last_status=status.to_dict(), last_probe_epoch=old)
        acc_good, f_good = _seed_folder(session, last_status=status.to_dict(), last_probe_epoch=old)
        session.commit()
        bad_id, good_id = acc_bad.id, acc_good.id

    def factory(account):
        if account.id == bad_id:
            return _FakeProbeProvider(None, fail=True)
        return _FakeProbeProvider(FolderStatus(messages=9, uidnext=10, unseen=5, highestmodseq=3))

    with Session() as session:
        result = schedule_folder_status_patrol(
            session, config=_cfg(), provider_factory=factory, now=now
        )
        session.commit()
        assert result.failed == 1
        assert result.changed == 1
        # The failing account is not marked failed by the patrol.
        acc = session.get(Account, bad_id)
        assert acc.sync_status != "failed"
        assert len(_delta_jobs(session, good_id, f_good.id)) == 1
        # The failed folder's attempt clock advanced (review f001):
        # it must not be retried on every scheduler sweep.
        cp_bad = session.get(
            SyncCheckpoint, {"account_id": bad_id, "folder_id": f_bad.id}
        )
        assert cp_bad.cursor["last_probe_at"] == now.timestamp()
        assert cp_bad.cursor["last_probe_failures"] == 1

    # An immediate re-sweep (60s scheduler cadence) must NOT re-probe
    # the failed folder: it retries next patrol cycle, not next sweep.
    bad_provider = _FakeProbeProvider(None, fail=True)
    with Session() as session:
        result2 = schedule_folder_status_patrol(
            session,
            config=_cfg(),
            provider_factory=lambda account: bad_provider,
            now=now + timedelta(seconds=60),
        )
        session.commit()
        assert result2.failed == 0
        assert bad_provider.probed == []


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_ac013_ac014_failing_folders_do_not_starve_others():
    """Review f001 regression: a failing set >= the per-sweep cap must
    not monopolise every sweep — attempt clocks advance on failure, so
    the remaining folders rotate in on the next sweep."""
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    old = (now - timedelta(seconds=5000)).timestamp()
    status = FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)
    remote_ids: list[str] = []
    with Session() as session:
        for _ in range(3):
            _acc, folder = _seed_folder(
                session, last_status=status.to_dict(), last_probe_epoch=old
            )
            remote_ids.append(folder.remote_id)
        session.commit()

    failing = _FakeProbeProvider(None, fail=True)
    with Session() as session:
        r1 = schedule_folder_status_patrol(
            session,
            config=_cfg(max_probes=2),
            provider_factory=lambda account: failing,
            now=now,
        )
        session.commit()
        assert r1.failed == 2
        first_pair = set(failing.probed)
        assert len(first_pair) == 2
    with Session() as session:
        r2 = schedule_folder_status_patrol(
            session,
            config=_cfg(max_probes=2),
            provider_factory=lambda account: failing,
            now=now + timedelta(seconds=60),
        )
        session.commit()
        # The third folder — never attempted — is probed now even
        # though the first pair keeps failing.
        assert r2.failed == 1
        assert failing.probed[-1] not in first_pair
        assert set(failing.probed) == set(remote_ids)


@pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)
def test_patrol_disabled_is_noop():
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    provider = _FakeProbeProvider(FolderStatus(messages=1))
    with Session() as session:
        _seed_folder(session)
        session.commit()
    with Session() as session:
        result = schedule_folder_status_patrol(
            session,
            config=_cfg(enabled=False),
            provider_factory=lambda account: provider,
            now=datetime.now(timezone.utc),
        )
        session.commit()
        assert result.probed == 0
        assert provider.probed == []
