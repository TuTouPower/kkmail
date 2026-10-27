"""Config loading and environment mapping for mail-core (t058)."""

from __future__ import annotations

import os
from typing import Mapping

from mail_core.config.models import ConfigError, MailCoreConfig

_BOOL_TRUE = frozenset({"1", "true", "yes", "on"})
_BOOL_FALSE = frozenset({"0", "false", "no", "off"})


def _parse_bool(val: str | None, default: bool) -> bool:
    if val is None or not str(val).strip():
        return default
    cleaned = str(val).strip().lower()
    if cleaned in _BOOL_TRUE:
        return True
    if cleaned in _BOOL_FALSE:
        return False
    return default


def _parse_optional_bool(val: str | None) -> bool | None:
    if val is None or not str(val).strip():
        return None
    cleaned = str(val).strip().lower()
    if cleaned in _BOOL_TRUE:
        return True
    if cleaned in _BOOL_FALSE:
        return False
    return None


def _parse_int(val: str | None, default: int, field_name: str) -> int:
    if val is None or not str(val).strip():
        return default
    try:
        return int(str(val).strip())
    except ValueError:
        raise ConfigError(f"invalid integer value for {field_name}: {val!r}") from None


def _parse_float(val: str | None, default: float, field_name: str) -> float:
    if val is None or not str(val).strip():
        return default
    try:
        return float(str(val).strip())
    except ValueError:
        raise ConfigError(f"invalid float value for {field_name}: {val!r}") from None


def load_config(env: Mapping[str, str] | None = None) -> MailCoreConfig:
    """Load configuration from environment dictionary (defaults to os.environ)."""
    source = os.environ if env is None else env

    config = MailCoreConfig(
        host=source.get("MAIL_CORE_HOST") or "127.0.0.1",
        port=_parse_int(source.get("MAIL_CORE_PORT"), 8000, "port"),
        data_dir=source.get("MAIL_CORE_DATA_DIR") or "",
        public_origin=source.get("MAIL_CORE_PUBLIC_ORIGIN") or "",
        allow_loopback_oauth_origin=_parse_bool(source.get("MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN"), False),
        allow_private_hosts=_parse_bool(source.get("MAIL_CORE_ALLOW_PRIVATE_HOSTS"), False),
        allow_test_providers=_parse_bool(source.get("MAIL_CORE_ALLOW_TEST_PROVIDERS"), False),
        forwarded_allow_ips=source.get("MAIL_CORE_FORWARDED_ALLOW_IPS") or None,
        proxy_headers=_parse_bool(source.get("MAIL_CORE_PROXY_HEADERS"), False),
        database_url=source.get("MAIL_CORE_DATABASE_URL") or "",
        db_pool_size=_parse_int(source.get("MAIL_CORE_DB_POOL_SIZE"), 10, "db_pool_size"),
        db_max_overflow=_parse_int(source.get("MAIL_CORE_DB_MAX_OVERFLOW"), 10, "db_max_overflow"),
        db_pool_timeout=_parse_float(source.get("MAIL_CORE_DB_POOL_TIMEOUT"), 30.0, "db_pool_timeout"),
        db_pool_recycle=_parse_int(source.get("MAIL_CORE_DB_POOL_RECYCLE"), 1800, "db_pool_recycle"),
        total_slots=_parse_int(source.get("MAIL_CORE_TOTAL_SLOTS"), 8, "total_slots"),
        background_start_slot=_parse_int(source.get("MAIL_CORE_BACKGROUND_START_SLOT"), 2, "background_start_slot"),
        capacity_retry_seconds=_parse_float(
            source.get("MAIL_CORE_CAPACITY_RETRY_SECONDS"), 5.0, "capacity_retry_seconds"
        ),
        max_mime_bytes=_parse_int(source.get("MAIL_CORE_MAX_MIME_BYTES"), 50 * 1024 * 1024, "max_mime_bytes"),
        max_attachment_bytes=_parse_int(
            source.get("MAIL_CORE_MAX_ATTACHMENT_BYTES"), 25 * 1024 * 1024, "max_attachment_bytes"
        ),
        archive_recent_days=_parse_int(
            source.get("MAIL_CORE_ARCHIVE_RECENT_DAYS"), 30, "archive_recent_days"
        ),
        archive_batch_size=_parse_int(source.get("MAIL_CORE_ARCHIVE_BATCH"), 20, "archive_batch_size"),
        embedded_worker=source.get("MAIL_CORE_EMBEDDED_WORKER") != "0",
        worker_id=source.get("MAIL_CORE_WORKER_ID") or None,
        worker_poll_s=_parse_float(source.get("MAIL_CORE_WORKER_POLL_S"), 2.0, "worker_poll_s"),
        worker_max_idle_s=_parse_float(source.get("MAIL_CORE_WORKER_MAX_IDLE_S"), 10.0, "worker_max_idle_s"),
        worker_heartbeat_s=_parse_float(source.get("MAIL_CORE_WORKER_HEARTBEAT_S"), 15.0, "worker_heartbeat_s"),
        worker_claim_batch=_parse_int(source.get("MAIL_CORE_CLAIM_BATCH"), 5, "worker_claim_batch"),
        worker_reclaim_interval_s=_parse_float(
            source.get("MAIL_CORE_RECLAIM_INTERVAL_S") or source.get("MAIL_CORE_RECLAIM_STALE_SECONDS"),
            60.0,
            "worker_reclaim_interval_s",
        ),
        inbox_poll_interval_s=_parse_float(
            source.get("MAIL_CORE_INBOX_POLL_INTERVAL_S"), 1200.0, "inbox_poll_interval_s"
        ),
        schedule_interval_s=_parse_float(
            source.get("MAIL_CORE_SCHEDULE_INTERVAL_S"), 60.0, "schedule_interval_s"
        ),
        secret_key=source.get("MAIL_CORE_SECRET_KEY") or "",
        session_max_age=_parse_int(source.get("MAIL_CORE_SESSION_MAX_AGE"), 30 * 86400, "session_max_age"),
        cookie_secure=_parse_optional_bool(source.get("MAIL_CORE_COOKIE_SECURE")),
        cookie_samesite=(source.get("MAIL_CORE_COOKIE_SAMESITE") or "lax").strip().lower(),
        login_max_failures=_parse_int(source.get("MAIL_CORE_LOGIN_MAX_FAILURES"), 10, "login_max_failures"),
        login_window_s=_parse_float(source.get("MAIL_CORE_LOGIN_WINDOW_S"), 300.0, "login_window_s"),
        sse_max_connections=_parse_int(source.get("MAIL_CORE_SSE_MAX_CONNECTIONS"), 128, "sse_max_connections"),
    )
    config.validate()
    return config
