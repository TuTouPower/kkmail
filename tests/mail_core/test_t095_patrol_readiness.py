"""t095: account-level patrol short-circuit and readiness probe contracts."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from mail_core.mail.domain.enums import FolderRemoteState
from mail_core.mail.domain.failures import StructuredFailure
from mail_core.mail.storage.models import Account, Folder
from mail_core.sync.patrol import PatrolConfig, schedule_folder_status_patrol

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _seed_account_two_folders(session, *, email_prefix: str = "t095patrol"):
    acc = Account(
        id=uuid.uuid4(),
        email=f"{email_prefix}-{uuid.uuid4().hex[:6]}@example.com",
        provider="stub",
        credential_ref=f"ref-{uuid.uuid4().hex[:6]}",
        sync_enabled=True,
    )
    session.add(acc)
    session.flush()
    folders = []
    for role in ("sent", "trash"):
        folder = Folder(
            id=uuid.uuid4(),
            account_id=acc.id,
            remote_id=f"remote-{role}-{uuid.uuid4().hex[:6]}",
            name=role,
            role=role,
            remote_state=FolderRemoteState.ACTIVE.value,
        )
        session.add(folder)
        folders.append(folder)
    session.flush()
    return acc, folders


class _FailOnceProvider:
    """Fails the first probe with a transport failure; records all attempts."""

    def __init__(self, exc: Exception):
        self.exc = exc
        self.probed: list[str] = []
        self.built = 0

    def probe_folder_status(self, folder_remote_id: str):
        self.probed.append(folder_remote_id)
        raise self.exc


def _cfg() -> PatrolConfig:
    return PatrolConfig(enabled=True, interval_s=0.0, max_probes=200, max_unprobed_s=0.0)


def test_ac004_transport_failure_short_circuits_remaining_folders():
    """A transport failure on one folder skips sibling folders this round."""
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    with Session() as session:
        acc, folders = _seed_account_two_folders(session)
        session.commit()
        acc_id = acc.id

    provider = _FailOnceProvider(ConnectionError("transport down"))
    with Session() as session:
        result = schedule_folder_status_patrol(
            session,
            config=_cfg(),
            provider_factory=lambda account: provider,
            now=datetime.now(timezone.utc),
        )
        session.commit()
        # Only one directory was actually probed; the sibling was skipped.
        assert len(provider.probed) == 1
        assert result.failed >= 1

    # Cross-round cooldown is held in account.config, not connectivity_state.
    with Session() as session:
        acc = session.get(Account, acc_id)
        assert acc.connectivity_state == "connected"  # t090 isolation preserved
        assert "patrol_cooldown_until" in (acc.config or {})


def test_ac006_committed_business_state_survives_restart_and_heartbeat_rebuild():
    """A committed business transaction is durable; a lost heartbeat rebuilds.

    Simulates process restart with a fresh session/engine. Synchronous commit
    (the t095 contract) guarantees the answered result is not lost; an
    independent heartbeat record can be re-created after loss.
    """
    from mail_core.db.session import get_session_factory
    from mail_core.mail.storage.models import AppSetting, OutboxEvent
    from mail_core.worker.heartbeat import HEARTBEAT_PREFIX, record_heartbeat

    Session = get_session_factory()
    acc_id = uuid.uuid4()
    hb_key = f"{HEARTBEAT_PREFIX}{acc_id}"
    with Session() as session:
        acc = Account(
            id=acc_id,
            email=f"durable-{uuid.uuid4().hex[:6]}@example.com",
            provider="stub",
            credential_ref="ref",
            sync_enabled=True,
        )
        session.add(acc)
        session.flush()
        session.add(
            OutboxEvent(event_type="sync.completed", payload={"account_id": str(acc_id)})
        )
        record_heartbeat(session, str(acc_id), active_jobs=0)
        session.commit()

    # Simulated restart: a brand-new session sees the committed business data.
    with Session() as session:
        assert session.get(Account, acc_id) is not None
        assert (
            session.scalar(
                select(OutboxEvent).where(OutboxEvent.event_type == "sync.completed")
            )
            is not None
        )
        assert session.get(AppSetting, hb_key) is not None

    # Heartbeat loss is reconstructible (disposable state).
    with Session() as session:
        session.execute(AppSetting.__table__.delete().where(AppSetting.key == hb_key))
        session.commit()
    with Session() as session:
        assert session.get(AppSetting, hb_key) is None
        record_heartbeat(session, str(acc_id), active_jobs=0)
        session.commit()
    with Session() as session:
        assert session.get(AppSetting, hb_key) is not None
