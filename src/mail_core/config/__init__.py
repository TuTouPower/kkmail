"""Centralized configuration module for mail-core (t058)."""

from __future__ import annotations

import threading
from typing import Mapping

from mail_core.config.loader import load_config
from mail_core.config.models import ConfigError, MailCoreConfig
from mail_core.net.bulkhead import configure_default_bulkhead

_lock = threading.Lock()
_current_config: MailCoreConfig | None = None


def _sync_runtime_bulkhead(config: MailCoreConfig) -> None:
    configure_default_bulkhead(
        failure_threshold=config.outbound_circuit_failure_threshold,
        cooldown_s=config.outbound_circuit_cooldown_s,
    )


def get_config() -> MailCoreConfig:
    """Return the cached configuration singleton, loading from os.environ on first call."""
    global _current_config
    if _current_config is None:
        with _lock:
            if _current_config is None:
                _current_config = load_config()
                _sync_runtime_bulkhead(_current_config)
    return _current_config


def set_config(config: MailCoreConfig) -> None:
    """Explicitly set the active configuration singleton (primarily for testing)."""
    global _current_config
    with _lock:
        _current_config = config
        _sync_runtime_bulkhead(config)


def reset_config(env: Mapping[str, str] | None = None) -> MailCoreConfig | None:
    """Reset configuration singleton to None, or re-load if env is provided."""
    global _current_config
    with _lock:
        if env is not None:
            _current_config = load_config(env)
            _sync_runtime_bulkhead(_current_config)
        else:
            _current_config = None
        return _current_config


__all__ = [
    "ConfigError",
    "MailCoreConfig",
    "get_config",
    "load_config",
    "reset_config",
    "set_config",
]
