"""Centralized configuration module for mail-core (t058)."""

from __future__ import annotations

import threading
from typing import Mapping

from mail_core.config.loader import load_config
from mail_core.config.models import ConfigError, MailCoreConfig

_lock = threading.Lock()
_current_config: MailCoreConfig | None = None


def get_config() -> MailCoreConfig:
    """Return the cached configuration singleton, loading from os.environ on first call."""
    global _current_config
    if _current_config is None:
        with _lock:
            if _current_config is None:
                _current_config = load_config()
    return _current_config


def set_config(config: MailCoreConfig) -> None:
    """Explicitly set the active configuration singleton (primarily for testing)."""
    global _current_config
    with _lock:
        _current_config = config


def reset_config(env: Mapping[str, str] | None = None) -> MailCoreConfig:
    """Reset and re-load configuration singleton from environment."""
    global _current_config
    with _lock:
        _current_config = load_config(env)
        return _current_config


__all__ = [
    "ConfigError",
    "MailCoreConfig",
    "get_config",
    "load_config",
    "reset_config",
    "set_config",
]
