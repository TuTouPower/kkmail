"""t095 Finding 4 & AC-003/AC-004 real PG and stub-socket regression tests."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

import mail_core.sync.delta as delta_mod
from mail_core.accounts.health import mark_credential_invalid
from mail_core.db.session import get_engine, get_session_factory
from mail_core.mail.domain.enums import (
    ConnectivityState,
    CredentialState,
    ExecutionOrigin,
    FolderRemoteState,
    SyncActivity,
)
from mail_core.mail.storage.models import (
    Account,
    Folder,
    FolderPatrolStatus,
    SyncCheckpoint,
)
from mail_core.providers.base import DeltaPage, FolderStatus
from mail_core.providers.http import PermanentAuthError, RateLimitedError
from mail_core.sync.patrol import (
    PATROL_COOLDOWN_S,
    PatrolConfig,
    schedule_folder_status_patrol,
)

_PG_SKIP = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_patrol_account(
    session,
    *,
    roles: tuple[str, ...] = ("sent", "trash"),
    config: dict | None = None,
    with_inbox_baseline: bool = False,
) -> tuple[Account, dict[str, Folder]]:
    acc = Account(
        id=uuid.uuid4(),
        email=f"t095fix-{uuid.uuid4().hex[:8]}@example.test",
        provider="imap",
        credential_ref=f"ref-{uuid.uuid4().hex[:8]}",
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
        if with_inbox_baseline or role != "inbox":
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


def _patrol_cfg(*, interval_s: float = 0.0) -> PatrolConfig:
    return PatrolConfig(
        enabled=True,
        interval_s=interval_s,
        max_probes=200,
        max_unprobed_s=0.0,
    )


@_PG_SKIP
def test_patrol_releases_transaction_during_probe_and_preserves_concurrent_config_edits():
    """Finding 4: patrol holds no DB tx/pool conn during network probe and preserves concurrent Account.config edits."""
    Session = get_session_factory()
    with Session() as session:
        acc, folders = _seed_patrol_account(
            session,
            roles=("sent", "trash"),
            config={
                "outbound_proxy": "socks5://127.0.0.1:1080",
                "sync_settings": {"days": 30},
            },
        )
        acc_id = acc.id
        folder_ids = [f.id for f in folders.values()]
        session.commit()

    observed_during_failure_probe: dict[str, object] = {}
    probed_fail: list[str] = []

    with Session() as patrol:
        class _FailTransportProvider:
            def probe_folder_status(self, remote_id: str):
                probed_fail.append(remote_id)
                observed_during_failure_probe["in_tx"] = patrol.in_transaction()
                observed_during_failure_probe["checkedout_before_fg"] = (
                    get_engine().pool.checkedout()
                )
                with Session() as fg:
                    idle_in_tx = fg.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname = current_database() "
                            "AND pid <> pg_backend_pid() "
                            "AND state = 'idle in transaction'"
                        )
                    )
                    observed_during_failure_probe["idle_in_tx"] = int(idle_in_tx or 0)
                    row = fg.get(Account, acc_id)
                    row.config = {
                        **(row.config or {}),
                        "outbound_proxy": "socks5://127.0.0.1:1090",
                        "concurrent_fg_key": "keep-me",
                    }
                    fg.commit()
                raise ConnectionError("network unreachable")

        now = datetime.now(timezone.utc)
        res = schedule_folder_status_patrol(
            patrol,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _FailTransportProvider(),
            now=now,
        )
        patrol.commit()

    assert res.failed == 1
    assert len(probed_fail) == 1
    assert observed_during_failure_probe == {
        "in_tx": False,
        "checkedout_before_fg": 0,
        "idle_in_tx": 0,
    }

    with Session() as session:
        acc_row = session.get(Account, acc_id)
        assert acc_row.connectivity_state == ConnectivityState.CONNECTED.value
        assert "patrol_cooldown_until" in acc_row.config
        assert acc_row.config["outbound_proxy"] == "socks5://127.0.0.1:1090"
        assert acc_row.config["concurrent_fg_key"] == "keep-me"
        assert acc_row.config["sync_settings"] == {"days": 30}
        fps_rows = list(
            session.scalars(
                select(FolderPatrolStatus).where(
                    FolderPatrolStatus.folder_id.in_(folder_ids)
                )
            ).all()
        )
        assert len(fps_rows) == 1

    # Recovery after cooldown expires must ALSO run outside DB tx and preserve concurrent edits when clearing cooldown.
    observed_during_recovery: dict[str, object] = {}
    recovery_edited = False

    with Session() as patrol:
        class _HealthyProvider:
            def probe_folder_status(self, _remote_id: str):
                nonlocal recovery_edited
                if not recovery_edited:
                    recovery_edited = True
                    observed_during_recovery["in_tx"] = patrol.in_transaction()
                    observed_during_recovery["checkedout_before_fg"] = (
                        get_engine().pool.checkedout()
                    )
                    with Session() as fg:
                        idle_in_tx = fg.scalar(
                            text(
                                "SELECT count(*) FROM pg_stat_activity "
                                "WHERE datname = current_database() "
                                "AND pid <> pg_backend_pid() "
                                "AND state = 'idle in transaction'"
                            )
                        )
                        observed_during_recovery["idle_in_tx"] = int(idle_in_tx or 0)
                        row = fg.get(Account, acc_id)
                        row.config = {
                            **(row.config or {}),
                            "recovery_concurrent_edit": True,
                        }
                        fg.commit()
                return FolderStatus(messages=3, uidnext=4, unseen=1, highestmodseq=9)

        res2 = schedule_folder_status_patrol(
            patrol,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _HealthyProvider(),
            now=now + timedelta(seconds=PATROL_COOLDOWN_S + 5),
        )
        patrol.commit()

    assert res2.probed == 2
    assert res2.failed == 0
    assert observed_during_recovery == {
        "in_tx": False,
        "checkedout_before_fg": 0,
        "idle_in_tx": 0,
    }
    with Session() as session:
        acc_row = session.get(Account, acc_id)
        assert "patrol_cooldown_until" not in acc_row.config
        assert acc_row.config["outbound_proxy"] == "socks5://127.0.0.1:1090"
        assert acc_row.config["concurrent_fg_key"] == "keep-me"
        assert acc_row.config["sync_settings"] == {"days": 30}
        assert acc_row.config["recovery_concurrent_edit"] is True


@_PG_SKIP
@pytest.mark.parametrize("recovery_succeeds", [True, False])
def test_patrol_half_open_expired_cooldown_single_holder_across_workers(recovery_succeeds: bool):
    """AC-004: two concurrent workers racing after cooldown expiry yield strictly one half-open probe."""
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    expired_iso = (now - timedelta(seconds=10)).isoformat()
    with Session() as session:
        acc, _folders = _seed_patrol_account(
            session,
            roles=("sent",),
            config={"patrol_cooldown_until": expired_iso, "keep": "yes"},
        )
        acc_id = acc.id
        session.commit()

    entered_probe = threading.Event()
    release_probe = threading.Event()
    probe_calls: list[str] = []
    probe_lock = threading.Lock()
    results: dict[str, object] = {}

    def _run_worker(name: str, *, hold_inside_probe: bool) -> None:
        with Session() as session:
            class _Provider:
                def probe_folder_status(self, remote_id: str):
                    with probe_lock:
                        probe_calls.append(f"{name}:{remote_id}")
                    if hold_inside_probe:
                        entered_probe.set()
                        assert release_probe.wait(timeout=5.0)
                    if not recovery_succeeds:
                        raise ConnectionError("still unreachable")
                    return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

            res = schedule_folder_status_patrol(
                session,
                config=_patrol_cfg(),
                provider_factory=lambda _a: _Provider(),
                now=now,
            )
            session.commit()
            results[name] = res

    t1 = threading.Thread(target=_run_worker, args=("w1",), kwargs={"hold_inside_probe": True})
    t1.start()
    assert entered_probe.wait(timeout=5.0)

    # Worker 2 races while Worker 1 is actively executing the half-open probe.
    _run_worker("w2", hold_inside_probe=False)
    release_probe.set()
    t1.join(timeout=5.0)
    assert not t1.is_alive()

    assert len(probe_calls) == 1
    assert results["w1"].probed == (1 if recovery_succeeds else 0)
    assert results["w1"].failed == (0 if recovery_succeeds else 1)
    assert results["w2"].probed == 0
    assert results["w2"].failed == 0

    with Session() as session:
        acc_row = session.get(Account, acc_id)
        assert acc_row.config["keep"] == "yes"
        if recovery_succeeds:
            assert "patrol_cooldown_until" not in acc_row.config
        else:
            assert acc_row.config["patrol_cooldown_until"] != expired_iso


@_PG_SKIP
def test_patrol_auth_failure_invalidates_preserves_config_and_isolates_shared_endpoint():
    """AC-004: AUTH failure invalidates acc_a, preserves config, skips siblings, and spares shared-endpoint acc_b."""
    Session = get_session_factory()
    shared_cfg = {
        "imap_host": "imap.shared.example",
        "imap_port": 993,
        "outbound_proxy": "http://proxy.local:8080",
    }
    with Session() as session:
        acc_a, folders_a = _seed_patrol_account(session, roles=("sent", "trash"), config=shared_cfg)
        acc_b, folders_b = _seed_patrol_account(session, roles=("sent",), config=shared_cfg)
        acc_a_id, acc_b_id = acc_a.id, acc_b.id
        a_folder_ids = [f.id for f in folders_a.values()]
        session.commit()

    probed_by_account: dict[uuid.UUID, list[str]] = {acc_a_id: [], acc_b_id: []}

    def _factory(account: Account):
        class _Prov:
            def probe_folder_status(self, remote_id: str):
                probed_by_account[account.id].append(remote_id)
                if account.id == acc_a_id:
                    with Session() as fg:
                        row = fg.get(Account, acc_a_id)
                        row.config = {**(row.config or {}), "user_note": "preserve-on-auth-fail"}
                        fg.commit()
                    raise PermanentAuthError("invalid credentials")
                return FolderStatus(messages=5, uidnext=6, unseen=1, highestmodseq=10)

        return _Prov()

    now = datetime.now(timezone.utc)
    with Session() as patrol:
        res = schedule_folder_status_patrol(
            patrol,
            config=_patrol_cfg(),
            provider_factory=_factory,
            now=now,
        )
        patrol.commit()

    assert res.failed == 1
    assert res.probed == 1
    assert len(probed_by_account[acc_a_id]) == 1
    assert len(probed_by_account[acc_b_id]) == 1

    with Session() as session:
        row_a = session.get(Account, acc_a_id)
        row_b = session.get(Account, acc_b_id)
        assert row_a.credential_state == CredentialState.INVALID.value
        assert row_a.sync_enabled is False
        assert row_a.sync_activity == SyncActivity.IDLE.value
        assert row_a.config["outbound_proxy"] == "http://proxy.local:8080"
        assert row_a.config["user_note"] == "preserve-on-auth-fail"
        assert "last_synced_at" in row_a.config
        assert "patrol_cooldown_until" in row_a.config

        assert row_b.credential_state == CredentialState.VALID.value
        assert row_b.connectivity_state == ConnectivityState.CONNECTED.value
        assert row_b.sync_enabled is True
        assert "patrol_cooldown_until" not in (row_b.config or {})

        fps_a = list(
            session.scalars(
                select(FolderPatrolStatus).where(FolderPatrolStatus.folder_id.in_(a_folder_ids))
            ).all()
        )
        assert len(fps_a) == 1

    # Also verify direct mark_credential_invalid preserves concurrent committed Account.config edits even from stale session.
    with Session() as stale, Session() as concurrent:
        stale_b = stale.get(Account, acc_b_id)
        assert stale_b is not None
        conc_b = concurrent.get(Account, acc_b_id)
        conc_b.config = {**(conc_b.config or {}), "concurrent_proxy_edit": "socks5://127.0.0.1:9999"}
        concurrent.commit()

        mark_credential_invalid(stale, acc_b_id)
        stale.commit()

    with Session() as session:
        refreshed_b = session.get(Account, acc_b_id)
        assert refreshed_b.credential_state == CredentialState.INVALID.value
        assert refreshed_b.sync_enabled is False
        assert refreshed_b.config["concurrent_proxy_edit"] == "socks5://127.0.0.1:9999"
        assert "last_synced_at" in refreshed_b.config


@_PG_SKIP
def test_patrol_single_folder_unknown_error_does_not_short_circuit_account():
    """AC-004: single-folder UNKNOWN failure stays isolated to that folder and still probes siblings."""
    Session = get_session_factory()
    with Session() as session:
        acc, folders = _seed_patrol_account(session, roles=("sent", "trash"))
        acc_id = acc.id
        sent_id, trash_id = folders["sent"].id, folders["trash"].id
        sent_rid = folders["sent"].remote_id
        session.commit()

    probed: list[str] = []

    class _MixedProvider:
        def probe_folder_status(self, remote_id: str):
            probed.append(remote_id)
            if remote_id == sent_rid:
                raise RuntimeError("SELECT mailbox corrupt")
            return FolderStatus(messages=2, uidnext=3, unseen=0, highestmodseq=4)

    with Session() as session:
        res = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _MixedProvider(),
            now=datetime.now(timezone.utc),
        )
        session.commit()

    assert res.failed == 1
    assert res.probed == 1
    assert len(probed) == 2
    with Session() as session:
        row = session.get(Account, acc_id)
        assert row.credential_state == CredentialState.VALID.value
        assert row.connectivity_state == ConnectivityState.CONNECTED.value
        assert "patrol_cooldown_until" not in (row.config or {})
        assert session.get(FolderPatrolStatus, sent_id).last_probe_failures == 1
        assert session.get(FolderPatrolStatus, trash_id).last_probe_failures == 0


@_PG_SKIP
def test_patrol_rate_limited_control_error_does_not_mark_unreachable_and_slows_rotation():
    """AC-004: RateLimitedError (CONTROL) never marks UNREACHABLE/cooldown and slows folder rotation."""
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc, folders = _seed_patrol_account(session, roles=("sent", "trash"))
        acc_id = acc.id
        sent_id = folders["sent"].id
        sent_rid = folders["sent"].remote_id
        session.commit()

    class _RateLimitedProvider:
        def probe_folder_status(self, remote_id: str):
            if remote_id == sent_rid:
                raise RateLimitedError("429 too many requests", retry_after_seconds=30.0)
            return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

    with Session() as session:
        res = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(interval_s=1200.0),
            provider_factory=lambda _a: _RateLimitedProvider(),
            now=now,
        )
        session.commit()

    assert res.failed == 1
    assert res.probed == 1
    with Session() as session:
        row = session.get(Account, acc_id)
        assert row.connectivity_state == ConnectivityState.CONNECTED.value
        assert row.credential_state == CredentialState.VALID.value
        assert "patrol_cooldown_until" not in (row.config or {})
        fps_sent = session.get(FolderPatrolStatus, sent_id)
        assert fps_sent.last_probe_at == now
        assert fps_sent.last_probe_failures == 1

    # Next sweep within interval_s skips the rate-limited folder (slowed rotation).
    probed_again: list[str] = []

    class _RecorderProvider:
        def probe_folder_status(self, remote_id: str):
            probed_again.append(remote_id)
            return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

    with Session() as session:
        res2 = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(interval_s=1200.0),
            provider_factory=lambda _a: _RecorderProvider(),
            now=now + timedelta(seconds=60),
        )
        session.commit()

    assert res2.probed == 0
    assert res2.failed == 0
    assert res2.skipped_not_due >= 2
    assert probed_again == []


@_PG_SKIP
def test_foreground_sync_bypasses_active_patrol_cooldown(monkeypatch):
    """AC-004: foreground sync runs immediately even while patrol cooldown is active."""
    Session = get_session_factory()
    now = datetime.now(timezone.utc)
    with Session() as session:
        acc, folders = _seed_patrol_account(
            session,
            roles=("inbox", "sent"),
            with_inbox_baseline=True,
        )
        acc_id = acc.id
        inbox_id = folders["inbox"].id
        session.commit()

    class _FailPatrolProvider:
        def probe_folder_status(self, _rid: str):
            raise ConnectionError("patrol transport down")

    with Session() as session:
        r1 = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _FailPatrolProvider(),
            now=now,
        )
        session.commit()
    assert r1.failed == 1

    # Verify patrol itself respects active cooldown.
    with Session() as session:
        r2 = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _FailPatrolProvider(),
            now=now + timedelta(seconds=30),
        )
        session.commit()
    assert r2.probed == 0 and r2.failed == 0 and r2.skipped_not_due >= 1

    # Foreground sync must bypass patrol cooldown and execute immediately.
    delta_called: list[str] = []

    class _HealthyDeltaProvider:
        def delta_changes(self, remote_id: str, _cursor: dict):
            delta_called.append(remote_id)
            return DeltaPage(changes=[], next_cursor={"modseq": 2}, exhausted=True)

    monkeypatch.setattr(delta_mod, "build_provider", lambda *a, **k: _HealthyDeltaProvider())
    fg_res = delta_mod.sync_folder_delta(
        acc_id,
        inbox_id,
        worker_id="fg-worker",
        execution_origin=ExecutionOrigin.FOREGROUND,
    )
    assert fg_res["status"] == "ok"
    assert len(delta_called) == 1


@_PG_SKIP
def test_patrol_caller_open_tx_compatibility_without_premature_commit():
    """Caller-owned uncommitted fixture transaction stays uncommitted across patrol sweep."""
    Session = get_session_factory()
    with Session() as session:
        acc, folders = _seed_patrol_account(session, roles=("sent",), config={"keep": "tx"})
        acc_id = acc.id
        sent_id = folders["sent"].id
        assert session.in_transaction() is True

        class _FailProv:
            def probe_folder_status(self, _rid: str):
                raise ConnectionError("boom")

        res = schedule_folder_status_patrol(
            session,
            config=_patrol_cfg(),
            provider_factory=lambda _a: _FailProv(),
            now=datetime.now(timezone.utc),
        )
        assert res.failed == 1
        assert session.in_transaction() is True
        assert "patrol_cooldown_until" in (session.get(Account, acc_id).config or {})
        assert session.get(FolderPatrolStatus, sent_id) is not None
        session.rollback()

    with Session() as session:
        assert session.get(Account, acc_id) is None
