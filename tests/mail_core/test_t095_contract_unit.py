"""t095 unit contracts: runtime budget, readiness cache, liveness stamp, patrol cooldown.

No database dependency; runs in the fast unit gate.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mail_core import runtime_budget
from mail_core.config.models import MailCoreConfig
from mail_core.liveness import read_liveness_stamp, write_liveness_stamp
from mail_core.readiness import ReadinessProbe
from mail_core.sync.patrol import (
    PATROL_COOLDOWN_S,
    _cooldown_active,
    _set_cooldown,
)
from mail_core.mail.storage.models import Account


def test_single_runtime_budget_is_the_source_of_defaults():
    """AC-002: config defaults and the DB pool derive from one budget module."""
    assert MailCoreConfig().db_pool_size == runtime_budget.DEFAULT_DB_POOL_SIZE
    assert MailCoreConfig().db_max_overflow == runtime_budget.DEFAULT_DB_MAX_OVERFLOW
    assert MailCoreConfig().total_slots == runtime_budget.DEFAULT_TOTAL_SLOTS
    assert MailCoreConfig().idle_quota == runtime_budget.DEFAULT_IDLE_QUOTA
    # Single-host defaults were tightened from the historical 10/10 and 32.
    assert runtime_budget.DEFAULT_DB_POOL_SIZE <= 4
    assert runtime_budget.DEFAULT_IDLE_QUOTA <= 8
    assert runtime_budget.MAX_CLIENT_CONNECTIONS >= (
        runtime_budget.DEFAULT_DB_POOL_SIZE
        + runtime_budget.DEFAULT_DB_MAX_OVERFLOW
        + 2  # outbox + job LISTEN direct connections
    )


def test_readiness_cache_ttl_and_worker_signal():
    """AC-005: readiness caches only the worker signal within a short TTL."""
    probe = ReadinessProbe(ttl_s=0.1)
    assert probe.cached_worker_active() is None
    snap = probe.snapshot(
        schema_revision="20261128_0008", listener_ready=True, worker_active=True
    )
    assert snap.worker_active is True
    assert probe.cached_worker_active() is True
    time.sleep(0.12)
    assert probe.cached_worker_active() is None
    probe.invalidate()
    assert probe.cached_worker_active() is None


def test_liveness_stamp_atomic_write_and_read(tmp_path):
    """AC-005: liveness stamp is atomically written and readable."""
    path = tmp_path / "liveness.json"
    write_liveness_stamp(path, progress=42, worker_id="w-1")
    stamp = read_liveness_stamp(path)
    assert stamp is not None
    assert stamp["progress"] == 42
    assert stamp["worker_id"] == "w-1"
    assert read_liveness_stamp(tmp_path / "missing.json") is None


def test_patrol_cooldown_lifecycle():
    """AC-004: a failed account holds a cross-round cooldown in account.config."""
    acc = Account(
        id=__import__("uuid").uuid4(),
        email="patrol-cool@example.com",
        provider="stub",
        credential_ref="ref",
        config={},
    )
    now = datetime.now(timezone.utc)
    assert _cooldown_active(acc, now) is False
    _set_cooldown(acc, now)
    assert _cooldown_active(acc, now) is True
    assert _cooldown_active(acc, now + timedelta(seconds=PATROL_COOLDOWN_S + 1)) is False


def test_healthcheck_uses_stamp_not_db(monkeypatch, tmp_path):
    """AC-005: worker healthcheck verifies the stamp without DB imports."""
    from mail_core.worker.healthcheck import main as hc_main

    path = tmp_path / "liveness.json"
    monkeypatch.setenv("MAIL_CORE_LIVENESS_STAMP", str(path))
    # No stamp -> unhealthy.
    assert hc_main() == 1
    write_liveness_stamp(path, progress=1, worker_id="w")
    assert hc_main() == 0


def test_ac003_idle_threads_bounded_by_quota_not_account_count():
    """AC-003: IDLE seat count (=> thread count) is capped by the quota."""
    import uuid as _uuid

    from mail_core.sync.idle_watcher import IdleCandidate, select_idle_holders

    now = datetime.now(timezone.utc)
    candidates = [
        IdleCandidate(
            account_id=_uuid.uuid4(),
            folder_id=_uuid.uuid4(),
            inbox_latest_arrival_at=now,
            inbox_has_messages=True,
            other_latest_arrival_at=None,
            account_created_at=now,
            credential_fingerprint=f"fp-{i}",
        )
        for i in range(50)
    ]
    holders = select_idle_holders(
        candidates,
        current_holders=set(),
        quota=runtime_budget.DEFAULT_IDLE_QUOTA,
        hysteresis_s=300.0,
        now=now,
    )
    assert len(holders) <= runtime_budget.DEFAULT_IDLE_QUOTA
    # Watcher + per-session reader => 2 threads per seat, fixed ceiling.
    assert len(holders) * 2 <= 2 * runtime_budget.DEFAULT_IDLE_QUOTA


def test_ac006_business_transactions_stay_synchronous():
    """AC-006: no business path opts into asynchronous commit."""
    repo_root = Path(__file__).resolve().parents[2]
    src = repo_root / "src/mail_core"
    offenders: list[str] = []
    for path in src.rglob("*.py"):
        if "test" in path.name:
            continue
        text = path.read_text(errors="ignore")
        if "synchronous_commit" in text and "off" in text:
            offenders.append(str(path.relative_to(repo_root)))
    assert offenders == [], f"async commit in business path: {offenders}"


def test_ac006_checkpoint_tuning_contract():
    """AC-006: checkpoint tuning target and durability policy are declared."""
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    compose = (repo_root / "docker-compose.embedded.yml").read_text()
    assert "checkpoint_timeout=15min" in compose
    # Durability is never traded away for the checkpoint tuning.
    assert "synchronous_commit=off" not in compose
