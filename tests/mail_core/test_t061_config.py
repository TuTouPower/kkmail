"""t061 AC-015: centralized config for IDLE watcher + folder status patrol."""

from __future__ import annotations

import pytest

from mail_core.config.loader import load_config
from mail_core.config.models import ConfigError


def test_t061_config_defaults():
    cfg = load_config({})
    assert cfg.idle_enabled is True
    assert cfg.idle_quota == 32
    assert cfg.idle_max_duration_s == 1680.0
    assert cfg.idle_backoff_base_s == 5.0
    assert cfg.idle_backoff_max_s == 300.0
    assert cfg.idle_hysteresis_s == 300.0
    assert cfg.folder_patrol_enabled is True
    assert cfg.folder_patrol_interval_s == 1200.0
    assert cfg.folder_patrol_max_probes == 200
    assert cfg.folder_patrol_max_unprobed_s == 2400.0


def test_t061_config_env_overrides():
    cfg = load_config(
        {
            "MAIL_CORE_IDLE_ENABLED": "0",
            "MAIL_CORE_IDLE_QUOTA": "8",
            "MAIL_CORE_IDLE_MAX_DURATION_S": "900",
            "MAIL_CORE_IDLE_BACKOFF_BASE_S": "1.5",
            "MAIL_CORE_IDLE_BACKOFF_MAX_S": "60",
            "MAIL_CORE_IDLE_HYSTERESIS_S": "120",
            "MAIL_CORE_FOLDER_PATROL_ENABLED": "false",
            "MAIL_CORE_FOLDER_PATROL_INTERVAL_S": "600",
            "MAIL_CORE_FOLDER_PATROL_MAX_PROBES": "50",
            "MAIL_CORE_FOLDER_PATROL_MAX_UNPROBED_S": "1800",
        }
    )
    assert cfg.idle_enabled is False
    assert cfg.idle_quota == 8
    assert cfg.idle_max_duration_s == 900.0
    assert cfg.idle_backoff_base_s == 1.5
    assert cfg.idle_backoff_max_s == 60.0
    assert cfg.idle_hysteresis_s == 120.0
    assert cfg.folder_patrol_enabled is False
    assert cfg.folder_patrol_interval_s == 600.0
    assert cfg.folder_patrol_max_probes == 50
    assert cfg.folder_patrol_max_unprobed_s == 1800.0


def test_t061_config_rejects_invalid_values():
    with pytest.raises(ConfigError):
        load_config({"MAIL_CORE_IDLE_QUOTA": "0"})
    with pytest.raises(ConfigError):
        load_config({"MAIL_CORE_IDLE_MAX_DURATION_S": "-5"})
    with pytest.raises(ConfigError):
        load_config({"MAIL_CORE_IDLE_BACKOFF_MAX_S": "1", "MAIL_CORE_IDLE_BACKOFF_BASE_S": "10"})
    with pytest.raises(ConfigError):
        load_config({"MAIL_CORE_FOLDER_PATROL_MAX_PROBES": "0"})
    with pytest.raises(ConfigError):
        load_config(
            {
                "MAIL_CORE_FOLDER_PATROL_INTERVAL_S": "1200",
                "MAIL_CORE_FOLDER_PATROL_MAX_UNPROBED_S": "600",
            }
        )
