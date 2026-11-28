"""t096 PostgreSQL integration tests: startup migration lock release, 0008 backfill, patrol zero-write short-circuit."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from mail_core import __main__ as main_module
from mail_core.db import baseline
from mail_core.mail.domain.enums import FolderRemoteState
from mail_core.mail.storage.models import (
    Account,
    AccountPatrolState,
    Folder,
    FolderPatrolStatus,
)
from mail_core.providers.base import FolderStatus
from mail_core.sync.patrol import (
    PATROL_COOLDOWN_S,
    PatrolConfig,
    schedule_folder_status_patrol,
)

ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = str(ROOT / "src/mail_core/db/alembic.ini")

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _alembic_cfg(url: str) -> Config:
    cfg = Config(ALEMBIC_INI)
    cfg.set_main_option("script_location", str(ROOT / "src/mail_core/db/alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def test_ac001_run_migrations_closes_check_connection_before_upgrade(monkeypatch):
    """AC-001: run_migrations closes the read-only check transaction before any write phase."""
    parsed = make_url(os.environ["MAIL_CORE_DATABASE_URL"])
    db_name = f"kkmail_t096_lock_{uuid.uuid4().hex[:16]}"
    admin_url = parsed.set(database="postgres").render_as_string(hide_password=False)
    temp_url = parsed.set(database=db_name).render_as_string(hide_password=False)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))

        monkeypatch.setenv("MAIL_CORE_DATABASE_URL", temp_url)
        idle_during_upgrade: list[int] = []
        orig_upgrade = command.upgrade

        def _spy_upgrade(cfg, rev):
            with admin.connect() as probe:
                count = probe.execute(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = :db AND state = 'idle in transaction'"
                    ),
                    {"db": db_name},
                ).scalar_one()
                idle_during_upgrade.append(int(count))
            return orig_upgrade(cfg, rev)

        monkeypatch.setattr("alembic.command.upgrade", _spy_upgrade)
        main_module.run_migrations()
        assert idle_during_upgrade == [0]
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        admin.dispose()


def test_ac001_migration_0008_backfills_last_delta_settled_at_from_updated_at():
    """AC-001: upgrading 20261126_0007 -> 20261128_0008 backfills last_delta_settled_at = updated_at."""
    parsed = make_url(os.environ["MAIL_CORE_DATABASE_URL"])
    db_name = f"kkmail_t096_bf_{uuid.uuid4().hex[:16]}"
    admin_url = parsed.set(database="postgres").render_as_string(hide_password=False)
    temp_url = parsed.set(database=db_name).render_as_string(hide_password=False)
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT", poolclass=NullPool)
    target = create_engine(temp_url, poolclass=NullPool)
    cfg = _alembic_cfg(temp_url)
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))

        command.upgrade(cfg, "20261126_0007")
        acc_id = uuid.uuid4()
        f1 = uuid.uuid4()
        f2 = uuid.uuid4()
        ts1 = datetime(2026, 11, 20, 8, 15, 30, tzinfo=timezone.utc)
        ts2 = datetime(2026, 11, 25, 19, 45, 0, tzinfo=timezone.utc)

        with target.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO accounts (id, email, provider, sync_enabled) "
                    "VALUES (:id, 'backfill@example.test', 'imap', true)"
                ),
                {"id": acc_id},
            )
            for fid, rid, name in ((f1, "INBOX", "Inbox"), (f2, "Sent", "Sent")):
                conn.execute(
                    text(
                        "INSERT INTO folders (id, account_id, remote_id, name, role, kind, selectable, remote_state) "
                        "VALUES (:id, :aid, :rid, :name, 'inbox', 'container', true, 'active')"
                    ),
                    {"id": fid, "aid": acc_id, "rid": rid, "name": name},
                )
            conn.execute(
                text(
                    "INSERT INTO sync_checkpoints "
                    "(account_id, folder_id, cursor, full_scan_complete, updated_at) "
                    "VALUES (:aid, :fid, '{}'::jsonb, true, :ts)"
                ),
                [
                    {"aid": acc_id, "fid": f1, "ts": ts1},
                    {"aid": acc_id, "fid": f2, "ts": ts2},
                ],
            )

        command.upgrade(cfg, baseline.CURRENT_HEAD_REVISION)

        with target.connect() as conn:
            rows = {
                row[0]: (row[1], row[2])
                for row in conn.execute(
                    text(
                        "SELECT folder_id, updated_at, last_delta_settled_at "
                        "FROM sync_checkpoints WHERE account_id = :aid"
                    ),
                    {"aid": acc_id},
                ).all()
            }
        assert rows[f1][0] == ts1 and rows[f1][1] == ts1
        assert rows[f2][0] == ts2 and rows[f2][1] == ts2
    finally:
        target.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))
        admin.dispose()


def test_ac003_patrol_short_circuit_zero_patrol_writes_and_clears_cooldown_on_recovery():
    """AC-003: short-circuited sibling folders incur zero FolderPatrolStatus writes; recovery clears cooldown."""
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            id=uuid.uuid4(),
            email=f"t096patrol-{uuid.uuid4().hex[:6]}@example.com",
            provider="stub",
            credential_ref=f"ref-{uuid.uuid4().hex[:6]}",
            sync_enabled=True,
        )
        session.add(acc)
        session.flush()
        folder_ids: list[uuid.UUID] = []
        for role in ("sent", "trash", "archive"):
            folder = Folder(
                id=uuid.uuid4(),
                account_id=acc.id,
                remote_id=f"remote-{role}-{uuid.uuid4().hex[:6]}",
                name=role,
                role=role,
                remote_state=FolderRemoteState.ACTIVE.value,
            )
            session.add(folder)
            folder_ids.append(folder.id)
        session.commit()
        acc_id = acc.id

    class _Provider:
        def __init__(self, fail: bool):
            self.fail = fail
            self.probed: list[str] = []

        def probe_folder_status(self, remote_id: str):
            self.probed.append(remote_id)
            if self.fail:
                raise ConnectionError("network unreachable")
            return FolderStatus(messages=1, uidnext=2, unseen=0, highestmodseq=1)

    now = datetime.now(timezone.utc)
    failing = _Provider(fail=True)
    with Session() as session:
        res = schedule_folder_status_patrol(
            session,
            config=PatrolConfig(enabled=True, interval_s=0.0, max_probes=200, max_unprobed_s=0.0),
            provider_factory=lambda _a: failing,
            now=now,
        )
        session.commit()
        assert len(failing.probed) == 1
        assert res.failed == 1

    # Only the 1 probed failing folder has a FolderPatrolStatus row; the 2 skipped siblings had zero DB writes.
    with Session() as session:
        fps_rows = list(
            session.scalars(
                select(FolderPatrolStatus).where(FolderPatrolStatus.folder_id.in_(folder_ids))
            ).all()
        )
        assert len(fps_rows) == 1
        acc_obj = session.get(Account, acc_id)
        # t097: the cooldown is patrol state, never a config key.
        assert "patrol_cooldown_until" not in (acc_obj.config or {})
        assert session.get(AccountPatrolState, acc_id) is not None

    # After cooldown expires, recovery probe succeeds and clears the stale cooldown key.
    healthy = _Provider(fail=False)
    with Session() as session:
        res2 = schedule_folder_status_patrol(
            session,
            config=PatrolConfig(enabled=True, interval_s=0.0, max_probes=200, max_unprobed_s=0.0),
            provider_factory=lambda _a: healthy,
            now=now + timedelta(seconds=PATROL_COOLDOWN_S + 5),
        )
        session.commit()
        assert res2.probed == 3
        assert res2.failed == 0
        acc_obj = session.get(Account, acc_id)
        assert "patrol_cooldown_until" not in (acc_obj.config or {})
        # t097: the lease holder's recovery success cleared the patrol state.
        assert session.get(AccountPatrolState, acc_id) is None


def test_ac005_isolated_runtime_does_not_touch_shared_tmp_liveness(tmp_path):
    """AC-005: isolated_runtime redirects MAIL_CORE_LIVENESS_STAMP away from /tmp."""
    from mail_core.liveness import DEFAULT_STAMP_PATH, stamp_path

    env_val = os.environ.get("MAIL_CORE_LIVENESS_STAMP")
    assert env_val is not None
    assert env_val != DEFAULT_STAMP_PATH
    assert str(stamp_path()) == env_val
