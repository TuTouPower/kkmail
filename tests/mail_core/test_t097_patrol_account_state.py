"""t097 real-PG tests: account-level patrol failure settlement, fenced
half-open lease, legacy cooldown migration, and transaction boundaries.

Covers AC-001..AC-005 of docs/tasks/t097_account_patrol_failure_and_lease.
All tests run the production patrol entry against real PostgreSQL and
compare persisted state in a fresh session.
"""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import (
    ConnectivityState,
    CredentialState,
    FolderRemoteState,
    SyncActivity,
)
from mail_core.mail.storage.models import (
    Account,
    AccountPatrolState,
    Folder,
    FolderPatrolStatus,
    SyncCheckpoint,
)
from mail_core.providers.base import FolderStatus
from mail_core.providers.http import PermanentAuthError
from mail_core.sync.patrol import (
    PATROL_COOLDOWN_S,
    PatrolConfig,
    schedule_folder_status_patrol,
)

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = str(ROOT / "src/mail_core/db/alembic.ini")

_PG_SKIP = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _patrol_cfg(*, interval_s: float = 0.0) -> PatrolConfig:
    return PatrolConfig(
        enabled=True,
        interval_s=interval_s,
        max_probes=200,
        max_unprobed_s=0.0,
    )


def _seed_account(
    session,
    *,
    roles: tuple[str, ...] = ("sent", "trash", "archive"),
    config: dict | None = None,
    credential_ref: str | None = "ref-ok",
) -> tuple[Account, dict[str, Folder]]:
    acc = Account(
        id=uuid.uuid4(),
        email=f"t097-{uuid.uuid4().hex[:8]}@example.test",
        provider="imap",
        credential_ref=credential_ref,
        sync_enabled=True,
        connectivity_state=ConnectivityState.CONNECTED.value,
        credential_state=CredentialState.VALID.value,
        sync_activity=SyncActivity.IDLE.value,
        config=dict(config or {}),
    )
    session.add(acc)
    session.flush()
    folders: dict[str, Folder] = {}
    for role in roles:
        folder = Folder(
            id=uuid.uuid4(),
            account_id=acc.id,
            remote_id=f"{role.upper()}-{uuid.uuid4().hex[:6]}",
            name=role.title(),
            role=role,
            remote_state=FolderRemoteState.ACTIVE.value,
        )
        session.add(folder)
        session.flush()
        session.add(
            SyncCheckpoint(
                account_id=acc.id,
                folder_id=folder.id,
                cursor={"modseq": 1},
                full_scan_complete=True,
            )
        )
        folders[role] = folder
    session.flush()
    return acc, folders


def _state(session, account_id: uuid.UUID) -> AccountPatrolState | None:
    return session.get(AccountPatrolState, account_id)


# ---------------------------------------------------------------------------
# AC-001: provider build settles once per account
# ---------------------------------------------------------------------------


@_PG_SKIP
def test_ac001_build_failure_settles_once_per_account_with_zero_folder_writes():
    """AC-001: a config-class build failure (missing IMAP credential ref)
    builds at most once, writes zero folder probe records and zero STATUS,
    settles once at account level, and does not affect other accounts."""
    Session = get_session_factory()
    with Session() as session:
        bad, bad_folders = _seed_account(session, credential_ref=None)
        good, _good_folders = _seed_account(session, roles=("sent",))
        bad_id, good_id = bad.id, good.id
        bad_folder_ids = [f.id for f in bad_folders.values()]
        session.commit()

    build_calls: list[uuid.UUID] = []

    class _HealthyProvider:
        def probe_folder_status(self, _remote_id: str):
            return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

    def _factory(account: Account):
        build_calls.append(account.id)
        if account.id == bad_id:
            # The real factory raises exactly this for a missing ref.
            raise ValueError("imap account missing credential_ref")
        return _HealthyProvider()

    now = datetime.now(timezone.utc)
    with Session() as session:
        res = schedule_folder_status_patrol(
            session, config=_patrol_cfg(), provider_factory=_factory, now=now
        )
        session.commit()

    assert build_calls.count(bad_id) == 1
    assert res.failed == 1
    assert res.probed == 1  # only the healthy account's folder

    with Session() as session:
        fps_rows = list(
            session.scalars(
                select(FolderPatrolStatus).where(
                    FolderPatrolStatus.folder_id.in_(bad_folder_ids)
                )
            ).all()
        )
        assert fps_rows == []
        state = _state(session, bad_id)
        assert state is not None
        assert state.cooldown_until is not None
        assert abs((state.cooldown_until - now).total_seconds() - PATROL_COOLDOWN_S) < 5
        assert state.lease_token is None
        bad_row = session.get(Account, bad_id)
        assert "patrol_cooldown_until" not in (bad_row.config or {})
        assert bad_row.credential_state == CredentialState.VALID.value
        assert _state(session, good_id) is None

    # Within the cooldown the account is not even rebuilt.
    build_calls.clear()
    with Session() as session:
        res2 = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=_factory,
            now=now + timedelta(seconds=30),
        )
        session.commit()
    assert build_calls.count(bad_id) == 0
    assert res2.skipped_not_due >= 3
    assert res2.failed == 0


@_PG_SKIP
def test_ac001_build_auth_failure_invalidates_credential_once():
    """AC-001: a permanent auth failure raised while building the provider
    still settles at account level: credential invalidated, one cooldown,
    zero folder probe records."""
    Session = get_session_factory()
    with Session() as session:
        acc, folders = _seed_account(session)
        acc_id = acc.id
        folder_ids = [f.id for f in folders.values()]
        session.commit()

    builds: list[int] = []

    def _factory(_account: Account):
        builds.append(1)
        raise PermanentAuthError("535 authentication failed")

    with Session() as session:
        res = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=_factory,
            now=datetime.now(timezone.utc),
        )
        session.commit()

    assert len(builds) == 1
    assert res.failed == 1
    assert res.probed == 0
    with Session() as session:
        row = session.get(Account, acc_id)
        assert row.credential_state == CredentialState.INVALID.value
        assert (
            session.scalars(
                select(FolderPatrolStatus).where(
                    FolderPatrolStatus.folder_id.in_(folder_ids)
                )
            ).all()
            == []
        )
        state = _state(session, acc_id)
        assert state is not None and state.cooldown_until is not None


# ---------------------------------------------------------------------------
# AC-002: an actual probe settles only its own folder record
# ---------------------------------------------------------------------------


@_PG_SKIP
def test_ac002_probe_transport_fault_records_only_the_probed_folder():
    """AC-002: the first probe hits an account-level transport fault; only
    that probe updates folder state. Pre-existing sibling rows keep their
    exact last_probe_at/failures, missing rows stay missing, and the
    background fault leaves connectivity_state untouched."""
    Session = get_session_factory()
    t0 = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
    with Session() as session:
        acc, folders = _seed_account(session)
        acc_id = acc.id
        probed_id = folders["sent"].id
        sibling_existing_id = folders["trash"].id
        sibling_missing_id = folders["archive"].id
        session.add(
            FolderPatrolStatus(
                folder_id=sibling_existing_id,
                last_status={"messages": 7},
                last_probe_at=t0,
                last_probe_failures=3,
            )
        )
        session.commit()

    probe_calls: list[str] = []

    class _TransportDownProvider:
        def probe_folder_status(self, remote_id: str):
            probe_calls.append(remote_id)
            raise ConnectionError("network unreachable")

    now = datetime.now(timezone.utc)
    with Session() as session:
        res = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _TransportDownProvider(),
            now=now,
        )
        session.commit()

    assert res.failed == 1
    assert len(probe_calls) == 1
    with Session() as session:
        # Rotation order is folder-id based: exactly one of the two folders
        # without a pre-existing row was probed and recorded; the other
        # missing row stays missing.
        recorded = [
            fid
            for fid in (probed_id, sibling_missing_id)
            if session.get(FolderPatrolStatus, fid) is not None
        ]
        assert len(recorded) == 1
        hit = session.get(FolderPatrolStatus, recorded[0])
        assert hit is not None
        assert hit.last_probe_at == now
        assert hit.last_probe_failures == 1
        sibling = session.get(FolderPatrolStatus, sibling_existing_id)
        assert sibling is not None
        assert sibling.last_probe_at == t0
        assert sibling.last_probe_failures == 3
        row = session.get(Account, acc_id)
        assert row.connectivity_state == ConnectivityState.CONNECTED.value
        assert row.credential_state == CredentialState.VALID.value
        state = _state(session, acc_id)
        assert state is not None and state.cooldown_until is not None


@_PG_SKIP
def test_ac002_probe_auth_fault_invalidates_and_records_only_probed_folder():
    """AC-002: a permanent auth fault on an actual probe invalidates the
    credential and short-circuits the account; siblings are not probed."""
    Session = get_session_factory()
    with Session() as session:
        acc, folders = _seed_account(session, roles=("sent", "trash"))
        acc_id = acc.id
        folder_ids = {f.id for f in folders.values()}
        session.commit()

    probe_calls: list[str] = []

    class _AuthDownProvider:
        def probe_folder_status(self, remote_id: str):
            probe_calls.append(remote_id)
            raise PermanentAuthError("535 authentication failed")

    with Session() as session:
        res = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _AuthDownProvider(),
            now=datetime.now(timezone.utc),
        )
        session.commit()

    assert res.failed == 1
    assert len(probe_calls) == 1
    with Session() as session:
        row = session.get(Account, acc_id)
        assert row.credential_state == CredentialState.INVALID.value
        rows = list(
            session.scalars(
                select(FolderPatrolStatus).where(
                    FolderPatrolStatus.folder_id.in_(folder_ids)
                )
            ).all()
        )
        assert len(rows) == 1
        assert rows[0].last_probe_failures == 1


# ---------------------------------------------------------------------------
# AC-003: cooldown skip, single holder, fenced late settlement
# ---------------------------------------------------------------------------


@_PG_SKIP
def test_ac003_active_cooldown_skips_with_zero_probes_and_zero_folder_writes():
    """AC-003: while the cooldown is active a rescan counts skips and does
    no probes and no folder writes at all."""
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc, folders = _seed_account(session)
        acc_id = acc.id
        folder_ids = [f.id for f in folders.values()]
        session.add(
            AccountPatrolState(
                account_id=acc_id,
                cooldown_until=now + timedelta(seconds=PATROL_COOLDOWN_S),
            )
        )
        session.commit()

    probe_calls: list[str] = []

    class _RecorderProvider:
        def probe_folder_status(self, remote_id: str):
            probe_calls.append(remote_id)
            return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

    with Session() as session:
        res = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _RecorderProvider(),
            now=now + timedelta(seconds=60),
        )
        session.commit()

    assert probe_calls == []
    assert res.probed == 0 and res.failed == 0
    assert res.skipped_not_due >= 3
    with Session() as session:
        assert (
            session.scalars(
                select(FolderPatrolStatus).where(
                    FolderPatrolStatus.folder_id.in_(folder_ids)
                )
            ).all()
            == []
        )


@_PG_SKIP
def test_ac003_expired_holder_late_settlement_cannot_touch_new_lease():
    """AC-003: holder A's lease expires mid-probe; sweep B re-claims and
    settles a fresh cooldown. A's late success must not clear B's state.
    (A's late FAILURE is covered by the two variants below.)"""
    Session = get_session_factory()
    now0 = datetime.now(timezone.utc)
    with Session() as session:
        acc, _folders = _seed_account(session, roles=("sent",))
        acc_id = acc.id
        session.add(
            AccountPatrolState(
                account_id=acc_id,
                cooldown_until=now0 - timedelta(seconds=10),
            )
        )
        session.commit()

    entered_probe = threading.Event()
    release_probe = threading.Event()
    a_result: dict[str, object] = {}

    def _run_a() -> None:
        with Session() as session:

            class _SlowProvider:
                def probe_folder_status(self, _remote_id: str):
                    entered_probe.set()
                    assert release_probe.wait(timeout=10.0)
                    return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

            res = schedule_folder_status_patrol(
                session,
                config=_patrol_cfg(),
                provider_factory=lambda _a: _SlowProvider(),
                now=now0,
            )
            session.commit()
            a_result["res"] = res

    thread_a = threading.Thread(target=_run_a)
    thread_a.start()
    assert entered_probe.wait(timeout=10.0)

    # While A holds a live lease, another sweep sees the account as cooling.
    with Session() as session:
        mid = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: pytest.fail("must not build during live lease"),
            now=now0 + timedelta(seconds=10),
        )
        session.commit()
    assert mid.probed == 0 and mid.failed == 0 and mid.skipped_not_due >= 1

    # A's lease has expired: B re-claims, probes, fails with a transport
    # fault and settles a fresh cooldown under its own lease.
    b_now = now0 + timedelta(seconds=PATROL_COOLDOWN_S + 10)

    class _BProvider:
        def probe_folder_status(self, _remote_id: str):
            raise ConnectionError("still unreachable")

    with Session() as session:
        res_b = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _BProvider(),
            now=b_now,
        )
        session.commit()
    assert res_b.failed == 1
    expected_cooldown = b_now + timedelta(seconds=PATROL_COOLDOWN_S)
    with Session() as session:
        state = _state(session, acc_id)
        assert state is not None
        assert state.cooldown_until == expected_cooldown
        assert state.lease_token is None

    # A's probe finally returns success — far too late to clear anything.
    release_probe.set()
    thread_a.join(timeout=10.0)
    assert not thread_a.is_alive()
    assert a_result["res"].probed == 1

    with Session() as session:
        state = _state(session, acc_id)
        assert state is not None
        assert state.cooldown_until == expected_cooldown
        assert state.lease_token is None


@_PG_SKIP
def test_ac003_expired_holder_late_failure_cannot_overwrite_new_settlement():
    """AC-003 (late-failure variant): B re-claims after A's lease expires
    and settles a fresh cooldown via a probe failure. A's probe then
    fails late with a transport fault: A's stale-token settlement must
    not overwrite (or shorten) B's cooldown."""
    Session = get_session_factory()
    now0 = datetime.now(timezone.utc)
    with Session() as session:
        acc, _folders = _seed_account(session, roles=("sent",))
        acc_id = acc.id
        session.add(
            AccountPatrolState(
                account_id=acc_id,
                cooldown_until=now0 - timedelta(seconds=10),
            )
        )
        session.commit()

    entered_probe = threading.Event()
    release_probe = threading.Event()
    a_result: dict[str, object] = {}

    def _run_a() -> None:
        with Session() as session:

            class _SlowFailingProvider:
                def probe_folder_status(self, _remote_id: str):
                    entered_probe.set()
                    assert release_probe.wait(timeout=10.0)
                    raise ConnectionError("a fails late")

            res = schedule_folder_status_patrol(
                session,
                config=_patrol_cfg(),
                provider_factory=lambda _a: _SlowFailingProvider(),
                now=now0,
            )
            session.commit()
            a_result["res"] = res

    thread_a = threading.Thread(target=_run_a)
    thread_a.start()
    assert entered_probe.wait(timeout=10.0)

    # A's lease has expired: B re-claims, probes, fails with a transport
    # fault and settles a fresh cooldown under its own lease.
    b_now = now0 + timedelta(seconds=PATROL_COOLDOWN_S + 10)

    class _BProvider:
        def probe_folder_status(self, _remote_id: str):
            raise ConnectionError("still unreachable")

    with Session() as session:
        res_b = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _BProvider(),
            now=b_now,
        )
        session.commit()
    assert res_b.failed == 1
    expected_cooldown = b_now + timedelta(seconds=PATROL_COOLDOWN_S)
    with Session() as session:
        state = _state(session, acc_id)
        assert state is not None
        assert state.cooldown_until == expected_cooldown
        assert state.lease_token is None

    # A's probe finally fails — far too late to touch B's settlement.
    release_probe.set()
    thread_a.join(timeout=10.0)
    assert not thread_a.is_alive()
    assert a_result["res"].failed == 1

    with Session() as session:
        state = _state(session, acc_id)
        assert state is not None
        assert state.cooldown_until == expected_cooldown
        assert state.lease_token is None


@_PG_SKIP
def test_ac003_expired_holder_late_failure_cannot_resurrect_cleared_state():
    """AC-003 (late-failure variant): B re-claims after A's lease expires
    and its successful probe clears the patrol state entirely. A's probe
    then fails late: A's stale-token settlement must not resurrect a
    cooldown row."""
    Session = get_session_factory()
    now0 = datetime.now(timezone.utc)
    with Session() as session:
        acc, _folders = _seed_account(session, roles=("sent",))
        acc_id = acc.id
        session.add(
            AccountPatrolState(
                account_id=acc_id,
                cooldown_until=now0 - timedelta(seconds=10),
            )
        )
        session.commit()

    entered_probe = threading.Event()
    release_probe = threading.Event()
    a_result: dict[str, object] = {}

    def _run_a() -> None:
        with Session() as session:

            class _SlowFailingProvider:
                def probe_folder_status(self, _remote_id: str):
                    entered_probe.set()
                    assert release_probe.wait(timeout=10.0)
                    raise ConnectionError("a fails late")

            res = schedule_folder_status_patrol(
                session,
                config=_patrol_cfg(),
                provider_factory=lambda _a: _SlowFailingProvider(),
                now=now0,
            )
            session.commit()
            a_result["res"] = res

    thread_a = threading.Thread(target=_run_a)
    thread_a.start()
    assert entered_probe.wait(timeout=10.0)

    # A's lease has expired: B re-claims, probes successfully and clears
    # the patrol state as the current holder.
    b_now = now0 + timedelta(seconds=PATROL_COOLDOWN_S + 10)

    class _BProvider:
        def probe_folder_status(self, _remote_id: str):
            return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

    with Session() as session:
        res_b = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _BProvider(),
            now=b_now,
        )
        session.commit()
    assert res_b.probed == 1 and res_b.failed == 0
    with Session() as session:
        assert _state(session, acc_id) is None

    # A's probe finally fails — far too late to resurrect anything.
    release_probe.set()
    thread_a.join(timeout=10.0)
    assert not thread_a.is_alive()
    assert a_result["res"].failed == 1

    with Session() as session:
        assert _state(session, acc_id) is None


@_PG_SKIP
def test_ac003_holder_same_sweep_success_then_failure_reestablishes_cooldown():
    """AC-003 (self-clear path): the lease holder's first probe succeeds
    and clears the (expired) cooldown row; a later folder in the SAME
    sweep then hits an account-level transport fault. The holder's own
    settlement must re-establish a fresh cooldown — fencing must only
    reject settlements from a DIFFERENT lease generation, not the
    holder's own post-clear failure."""
    Session = get_session_factory()
    now0 = datetime.now(timezone.utc)
    with Session() as session:
        acc, folders = _seed_account(session, roles=("sent", "trash"))
        acc_id = acc.id
        session.add(
            AccountPatrolState(
                account_id=acc_id,
                cooldown_until=now0 - timedelta(seconds=10),
            )
        )
        # Rotation: the never-probed folder goes first (success), the
        # folder with a recent attempt goes second (failure).
        session.add(
            FolderPatrolStatus(
                folder_id=folders["trash"].id,
                last_probe_at=now0 - timedelta(seconds=5),
                last_probe_failures=0,
            )
        )
        ok_remote = folders["sent"].remote_id
        session.commit()

    class _MixedProvider:
        def probe_folder_status(self, remote_id: str):
            if remote_id == ok_remote:
                return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)
            raise ConnectionError("endpoint down")

    with Session() as session:
        res = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _MixedProvider(),
            now=now0,
        )
        session.commit()
    assert res.probed == 1 and res.failed == 1
    with Session() as session:
        state = _state(session, acc_id)
        assert state is not None
        assert state.cooldown_until == now0 + timedelta(seconds=PATROL_COOLDOWN_S)
        assert state.lease_token is None


@_PG_SKIP
def test_ac003_current_holder_success_clears_cooldown():
    """AC-003: the current lease holder's successful probe clears the
    cooldown state entirely."""
    Session = get_session_factory()
    now0 = datetime.now(timezone.utc)
    with Session() as session:
        acc, _folders = _seed_account(session, roles=("sent", "trash"))
        acc_id = acc.id
        session.add(
            AccountPatrolState(
                account_id=acc_id,
                cooldown_until=now0 - timedelta(seconds=10),
            )
        )
        session.commit()

    class _HealthyProvider:
        def probe_folder_status(self, _remote_id: str):
            return FolderStatus(messages=2, uidnext=3, unseen=0, highestmodseq=4)

    with Session() as session:
        res = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _HealthyProvider(),
            now=now0,
        )
        session.commit()
    assert res.probed == 2 and res.failed == 0
    with Session() as session:
        assert _state(session, acc_id) is None


# ---------------------------------------------------------------------------
# AC-004: legacy config cooldown migration
# ---------------------------------------------------------------------------


def _alembic_cfg(url: str) -> Config:
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option("script_location", str(ROOT / "src/mail_core/db/alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


@_PG_SKIP
def test_ac004_migration_moves_parseable_cooldowns_and_strips_legacy_key():
    """AC-004: parseable legacy cooldowns (tz-aware and naive) keep working
    via the new table after upgrade; every other config key/value is
    preserved byte-for-byte and the legacy key is gone everywhere.
    Downgrade restores the usable cooldowns into the legacy key."""
    parsed = make_url(os.environ["MAIL_CORE_DATABASE_URL"])
    db_name = f"kkmail_t097_mig_{uuid.uuid4().hex[:16]}"
    _render = {"hide_password": False}
    admin_url = parsed.set(database="postgres").render_as_string(**_render)
    temp_url = parsed.set(database=db_name).render_as_string(**_render)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    target = create_engine(temp_url, poolclass=NullPool)
    cfg = _alembic_cfg(temp_url)
    future = datetime(2027, 3, 1, 12, 0, tzinfo=timezone.utc)
    past = datetime(2026, 1, 15, 8, 30, tzinfo=timezone.utc)
    naive = datetime(2027, 6, 1, 0, 0)  # legacy naive values read as UTC
    ids = {name: uuid.uuid4() for name in ("future", "past", "naive", "bad", "plain")}
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
        command.upgrade(cfg, "20261128_0008")
        fixtures = {
            "future": {"patrol_cooldown_until": future.isoformat(), "keep": {"x": 1}, "other": "v"},
            "past": {"patrol_cooldown_until": past.isoformat()},
            "naive": {"patrol_cooldown_until": naive.isoformat()},
            "bad": {"patrol_cooldown_until": "not-a-date", "keep": 2},
            "plain": {"keep": 3},
        }
        with target.begin() as conn:
            for name, config in fixtures.items():
                conn.execute(
                    text(
                        "INSERT INTO accounts (id, email, provider, sync_enabled, config) "
                        "VALUES (:id, :email, 'imap', true, CAST(:cfg AS jsonb))"
                    ),
                    {
                        "id": ids[name],
                        "email": f"{name}@example.test",
                        "cfg": _json(config),
                    },
                )

        command.upgrade(cfg, "head")

        with target.connect() as conn:
            states = {
                row.account_id: row.cooldown_until
                for row in conn.execute(
                    text("SELECT account_id, cooldown_until FROM account_patrol_state")
                )
            }
            configs = {
                row.id: row.config
                for row in conn.execute(text("SELECT id, config FROM accounts"))
            }
        assert states[ids["future"]] == future
        assert states[ids["past"]] == past
        assert states[ids["naive"]] == naive.replace(tzinfo=timezone.utc)
        assert ids["bad"] not in states
        assert ids["plain"] not in states
        for name in ids:
            assert "patrol_cooldown_until" not in configs[ids[name]]
        assert configs[ids["future"]]["keep"] == {"x": 1}
        assert configs[ids["future"]]["other"] == "v"
        assert configs[ids["bad"]]["keep"] == 2
        assert configs[ids["plain"]] == {"keep": 3}

        command.downgrade(cfg, "20261128_0008")
        with target.connect() as conn:
            configs = {
                row.id: row.config
                for row in conn.execute(text("SELECT id, config FROM accounts"))
            }
            tables = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
                    )
                )
            }
        assert "account_patrol_state" not in tables
        restored = datetime.fromisoformat(configs[ids["future"]]["patrol_cooldown_until"])
        assert restored == future
        assert configs[ids["future"]]["keep"] == {"x": 1}
        assert "patrol_cooldown_until" not in configs[ids["bad"]]
        assert configs[ids["plain"]] == {"keep": 3}
    finally:
        target.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        admin.dispose()


def _json(obj: dict) -> str:
    import json

    return json.dumps(obj)


# ---------------------------------------------------------------------------
# AC-005: patrol transactions end before build / STATUS; config edits save
# ---------------------------------------------------------------------------


@_PG_SKIP
def test_ac005_build_and_probe_run_outside_transactions_and_claim_is_committed():
    """AC-005: at provider-build time the half-open claim is already
    committed (visible from a separate session) and neither the build nor
    the STATUS probe runs inside an open patrol transaction; a config
    edit submitted mid-patrol saves normally and survives."""
    Session = get_session_factory()
    now0 = datetime.now(timezone.utc)
    with Session() as session:
        acc, _folders = _seed_account(
            session, roles=("sent",), config={"outbound_proxy": "socks5://127.0.0.1:1080"}
        )
        acc_id = acc.id
        session.add(
            AccountPatrolState(
                account_id=acc_id,
                cooldown_until=now0 - timedelta(seconds=10),
            )
        )
        session.commit()

    observed: dict[str, object] = {}

    with Session() as patrol:

        def _factory(_account: Account):
            observed["build_in_tx"] = patrol.in_transaction()
            with Session() as other:
                state = other.get(AccountPatrolState, acc_id)
                observed["lease_visible_at_build"] = (
                    state is not None and state.lease_token is not None
                )
                idle_in_tx = other.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND pid <> pg_backend_pid() "
                        "AND state = 'idle in transaction'"
                    )
                )
                observed["idle_in_tx_at_build"] = int(idle_in_tx or 0)
                row = other.get(Account, acc_id)
                row.config = {**(row.config or {}), "concurrent_fg_key": "keep-me"}
                other.commit()

            class _Provider:
                def probe_folder_status(self, _remote_id: str):
                    observed["probe_in_tx"] = patrol.in_transaction()
                    return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

            return _Provider()

        res = schedule_folder_status_patrol(
            patrol, config=_patrol_cfg(), provider_factory=_factory, now=now0
        )
        patrol.commit()

    assert res.probed == 1 and res.failed == 0
    assert observed == {
        "build_in_tx": False,
        "lease_visible_at_build": True,
        "idle_in_tx_at_build": 0,
        "probe_in_tx": False,
    }
    with Session() as session:
        row = session.get(Account, acc_id)
        assert row.config["concurrent_fg_key"] == "keep-me"
        assert row.config["outbound_proxy"] == "socks5://127.0.0.1:1080"
        assert "patrol_cooldown_until" not in (row.config or {})
        # The holder's success cleared the state after the probe.
        assert _state(session, acc_id) is None
