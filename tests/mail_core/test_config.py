"""Unit tests for centralized configuration system (t058 AC-001 ~ AC-006)."""

from __future__ import annotations

import pytest

from mail_core.config import ConfigError, MailCoreConfig, load_config


def test_ac001_config_defaults():
    cfg = load_config({})
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8000
    assert cfg.db_pool_size == 10
    assert cfg.db_max_overflow == 10
    assert cfg.db_pool_timeout == 30.0
    assert cfg.db_pool_recycle == 1800
    assert cfg.total_slots == 8
    assert cfg.background_start_slot == 2
    assert cfg.capacity_retry_seconds == 5.0
    assert cfg.max_mime_bytes == 50 * 1024 * 1024
    assert cfg.max_attachment_bytes == 25 * 1024 * 1024
    assert cfg.archive_recent_days == 30
    assert cfg.worker_claim_batch == 5
    assert cfg.worker_reclaim_interval_s == 60.0
    assert cfg.worker_poll_s == 2.0
    assert cfg.worker_max_idle_s == 10.0
    assert cfg.inbox_poll_interval_s == 1200.0
    assert cfg.schedule_interval_s == 60.0


def test_ac002_connection_slots_override():
    env = {
        "MAIL_CORE_TOTAL_SLOTS": "16",
        "MAIL_CORE_BACKGROUND_START_SLOT": "4",
        "MAIL_CORE_CAPACITY_RETRY_SECONDS": "10.0",
    }
    cfg = load_config(env)
    assert cfg.total_slots == 16
    assert cfg.background_start_slot == 4
    assert cfg.capacity_retry_seconds == 10.0


def test_ac003_storage_limits_override():
    env = {
        "MAIL_CORE_MAX_MIME_BYTES": "104857600",
        "MAIL_CORE_MAX_ATTACHMENT_BYTES": "52428800",
        "MAIL_CORE_ARCHIVE_RECENT_DAYS": "60",
    }
    cfg = load_config(env)
    assert cfg.max_mime_bytes == 104857600
    assert cfg.max_attachment_bytes == 52428800
    assert cfg.archive_recent_days == 60


def test_ac004_and_ac005_worker_and_inbox_override():
    # t063 AC-011: MAIL_CORE_CLAIM_BATCH / worker_claim_batch removed in favor of concurrent executor
    env = {
        "MAIL_CORE_RECLAIM_INTERVAL_S": "120.0",
        "MAIL_CORE_WORKER_POLL_S": "5.0",
        "MAIL_CORE_INBOX_POLL_INTERVAL_S": "600.0",
        "MAIL_CORE_SCHEDULE_INTERVAL_S": "30.0",
    }
    cfg = load_config(env)
    assert not hasattr(cfg, "worker_claim_batch")
    assert cfg.worker_reclaim_interval_s == 120.0
    assert cfg.worker_poll_s == 5.0
    assert cfg.inbox_poll_interval_s == 600.0
    assert cfg.schedule_interval_s == 30.0


def test_ac006_config_validation_errors():
    # 1. Invalid port
    with pytest.raises(ConfigError, match="port"):
        load_config({"MAIL_CORE_PORT": "70000"})
    with pytest.raises(ConfigError, match="port"):
        load_config({"MAIL_CORE_PORT": "not_a_number"})

    # 2. Invalid slots
    with pytest.raises(ConfigError, match="total_slots"):
        load_config({"MAIL_CORE_TOTAL_SLOTS": "0"})
    with pytest.raises(ConfigError, match="background_start_slot"):
        load_config({"MAIL_CORE_TOTAL_SLOTS": "8", "MAIL_CORE_BACKGROUND_START_SLOT": "8"})

    # 3. Invalid storage limits
    with pytest.raises(ConfigError, match="max_mime_bytes"):
        load_config({"MAIL_CORE_MAX_MIME_BYTES": "-1"})

    # 4. Invalid retry seconds
    with pytest.raises(ConfigError, match="capacity_retry_seconds"):
        load_config({"MAIL_CORE_CAPACITY_RETRY_SECONDS": "0"})
