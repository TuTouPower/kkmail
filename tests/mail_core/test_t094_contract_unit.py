"""t094 pure-contract tests: settlement classification and retention constants.

No database dependency; runs in the fast unit gate.
"""

from __future__ import annotations

import inspect
from datetime import timedelta
from pathlib import Path

from mail_core.sync.checkpoints import is_delta_settled_result
from mail_core.worker.main import schedule_periodic_inbox_sync
from mail_core.sync.retention import (
    COMPLETED_JOB_PRUNE_BATCH,
    COMPLETED_JOB_RETENTION,
    MESSAGE_STATS_ANALYZE_COOLDOWN_SECONDS,
    MESSAGE_STATS_BULK_CHANGED_ROWS,
    MESSAGE_STATS_MIN_INTERVAL_S,
    MESSAGE_STATS_TABLES,
    PUBLISHED_OUTBOX_PRUNE_BATCH,
    PUBLISHED_OUTBOX_RETENTION,
    is_bulk_message_sync,
    reltuples_within_tolerance,
    refresh_table_stats_if_bulk,
)


def test_delta_settlement_classification():
    assert is_delta_settled_result({"status": "ok", "exhausted": True}) is True
    assert is_delta_settled_result({"status": "ok", "exhausted": False}) is False
    assert is_delta_settled_result({"status": "skipped", "reason": "baseline_required"}) is True
    assert is_delta_settled_result({"status": "sync_disabled"}) is True
    assert is_delta_settled_result({"status": "rate_limited", "retry_after": 5}) is False
    assert is_delta_settled_result(
        {"status": "capacity_unavailable", "followup_scheduled": True}
    ) is False
    assert is_delta_settled_result(
        {"status": "fencing_mismatch", "followup_scheduled": True}
    ) is False
    assert is_delta_settled_result(
        {"status": "cursor_invalid", "await_initialization": True}
    ) is False
    assert is_delta_settled_result({"status": "provider_error"}) is False
    assert is_delta_settled_result(
        {"status": "ok", "exhausted": True, "followup_scheduled": True}
    ) is False
    assert is_delta_settled_result(None) is False


def test_retention_windows_are_short_fixed_not_seven_days():
    assert COMPLETED_JOB_RETENTION == timedelta(hours=24)
    assert PUBLISHED_OUTBOX_RETENTION == timedelta(hours=24)
    assert COMPLETED_JOB_RETENTION < timedelta(days=7)
    assert PUBLISHED_OUTBOX_RETENTION < timedelta(days=7)
    assert COMPLETED_JOB_PRUNE_BATCH > 0
    assert PUBLISHED_OUTBOX_PRUNE_BATCH > 0


def test_stats_refresh_only_for_bulk_deletes_on_declared_tables():
    assert refresh_table_stats_if_bulk(1000, "worker_jobs") is True
    assert refresh_table_stats_if_bulk(999, "worker_jobs") is False
    assert refresh_table_stats_if_bulk(1000, "outbox") is True
    assert refresh_table_stats_if_bulk(1000, "messages") is False


def test_message_stats_contract_constants_consumed():
    """AC-006: bulk threshold and relative-error bound are declared and used."""
    assert MESSAGE_STATS_TABLES == ("message_search", "messages", "message_bodies")
    assert MESSAGE_STATS_ANALYZE_COOLDOWN_SECONDS == 300.0
    assert MESSAGE_STATS_MIN_INTERVAL_S == MESSAGE_STATS_ANALYZE_COOLDOWN_SECONDS
    assert is_bulk_message_sync(MESSAGE_STATS_BULK_CHANGED_ROWS) is True
    assert is_bulk_message_sync(MESSAGE_STATS_BULK_CHANGED_ROWS - 1) is False
    # Real row-count comparison: each table judged against its own count; a
    # stale estimate like the production 68-vs-22095 is rejected.
    assert reltuples_within_tolerance(22_000, 22_095) is True
    assert reltuples_within_tolerance(68, 22_095) is False
    assert reltuples_within_tolerance(-1, 22_095) is False
    assert reltuples_within_tolerance(0, 0) is True


def test_scheduler_source_has_no_worker_jobs_terminal_lookup():
    """AC-001: the periodic scheduler must not look up worker_jobs terminal rows.

    The authoritative watermark is the checkpoint; a terminal-history lookup
    was the second source of truth that caused the seq_scan storm.
    """
    src = inspect.getsource(schedule_periodic_inbox_sync)
    assert "latest_job_finished" not in src
    assert "WorkerJob.updated_at" not in src
    assert "last_delta_settled_at" in src


def test_migration_backfills_watermark_from_updated_at():
    """AC-002: upgrade backfills the new watermark from the checkpoint's
    updated_at so existing folders are never suddenly overdue. Source-level
    guard on the migration (the DB migration suite validates head schema)."""
    repo_root = Path(__file__).resolve().parents[2]
    migration = (
        repo_root
        / "src/mail_core/db/alembic/versions/20261128_0008_watermark_authority_and_queue_index.py"
    )
    text = migration.read_text()
    assert "last_delta_settled_at" in text
    assert "SET last_delta_settled_at = updated_at" in text


def test_ac003_retention_exceeds_in_flight_reclaim_and_convergence_bounds():
    """AC-003 quantitative bound: 24h retention >> 300s reclaim and 30m target convergence."""
    from mail_core.sync.execution import converge_stalled_targets
    from mail_core.sync.jobs import reclaim_stale_claims

    reclaim_default = inspect.signature(reclaim_stale_claims).parameters["older_than"].default
    converge_default = inspect.signature(converge_stalled_targets).parameters["stale_after"].default

    assert reclaim_default == timedelta(seconds=300)
    assert converge_default == timedelta(minutes=30)
    assert COMPLETED_JOB_RETENTION == timedelta(hours=24)
    assert PUBLISHED_OUTBOX_RETENTION == timedelta(hours=24)
    assert reclaim_default < converge_default
    assert converge_default * 48 <= COMPLETED_JOB_RETENTION
    assert converge_default * 48 <= PUBLISHED_OUTBOX_RETENTION
    assert reclaim_default * 288 <= COMPLETED_JOB_RETENTION
