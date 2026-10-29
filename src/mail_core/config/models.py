"""Data models for centralized mail-core configuration (t058)."""

from __future__ import annotations

from dataclasses import dataclass, field
import math


class ConfigError(ValueError):
    """Raised when configuration validation fails."""


@dataclass(frozen=True)
class MailCoreConfig:
    # Network & Server
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: str = ""
    public_origin: str = ""
    allow_loopback_oauth_origin: bool = False
    allow_private_hosts: bool = False
    allow_test_providers: bool = False
    forwarded_allow_ips: str | None = None
    proxy_headers: bool = False

    # Database & Pool
    database_url: str = ""
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout: float = 30.0
    db_pool_recycle: int = 1800

    # Provider Connection Slots
    total_slots: int = 8
    background_start_slot: int = 2
    capacity_retry_seconds: float = 5.0

    # Mail & Storage Limits
    max_mime_bytes: int = 50 * 1024 * 1024
    max_attachment_bytes: int = 25 * 1024 * 1024
    archive_recent_days: int = 30
    archive_batch_size: int = 20

    # Worker & Scheduling
    embedded_worker: bool = True
    worker_id: str | None = None
    worker_poll_s: float = 2.0
    worker_max_idle_s: float = 10.0
    worker_heartbeat_s: float = 15.0
    worker_reclaim_interval_s: float = 60.0
    inbox_poll_interval_s: float = 1200.0
    schedule_interval_s: float = 60.0

    # IDLE inbox watcher (t061). The quota is an independent budget for
    # long-lived IDLE connections only; it never consumes the
    # connection_slots task budget above.
    idle_enabled: bool = True
    idle_quota: int = 32
    idle_max_duration_s: float = 1680.0
    idle_backoff_base_s: float = 5.0
    idle_backoff_max_s: float = 300.0
    idle_hysteresis_s: float = 300.0

    # All-folder STATUS patrol (t061)
    folder_patrol_enabled: bool = True
    folder_patrol_interval_s: float = 1200.0
    folder_patrol_max_probes: int = 200
    folder_patrol_max_unprobed_s: float = 2400.0

    # Security & Rate Limiting
    secret_key: str = ""
    session_max_age: int = 30 * 86400
    cookie_secure: bool | None = None
    cookie_samesite: str = "lax"
    login_max_failures: int = 10
    login_window_s: float = 300.0
    sse_max_connections: int = 128

    def validate(self) -> None:
        """Validate numeric ranges and logical constraints."""
        if not (1 <= self.port <= 65535):
            raise ConfigError(f"invalid port: {self.port} (must be between 1 and 65535)")

        if self.total_slots <= 0:
            raise ConfigError(f"invalid total_slots: {self.total_slots} (must be > 0)")

        if not (0 <= self.background_start_slot < self.total_slots):
            raise ConfigError(
                f"invalid background_start_slot: {self.background_start_slot} (must be >= 0 and < total_slots {self.total_slots})"
            )

        if not math.isfinite(self.capacity_retry_seconds) or self.capacity_retry_seconds <= 0:
            raise ConfigError(f"invalid capacity_retry_seconds: {self.capacity_retry_seconds} (must be finite > 0)")

        if self.max_mime_bytes <= 0:
            raise ConfigError(f"invalid max_mime_bytes: {self.max_mime_bytes} (must be > 0)")

        if self.max_attachment_bytes <= 0:
            raise ConfigError(f"invalid max_attachment_bytes: {self.max_attachment_bytes} (must be > 0)")

        if self.db_pool_size <= 0:
            raise ConfigError(f"invalid db_pool_size: {self.db_pool_size} (must be > 0)")

        if self.db_max_overflow < 0:
            raise ConfigError(f"invalid db_max_overflow: {self.db_max_overflow} (must be >= 0)")

        if not math.isfinite(self.db_pool_timeout) or self.db_pool_timeout <= 0:
            raise ConfigError(f"invalid db_pool_timeout: {self.db_pool_timeout} (must be finite > 0)")

        if not math.isfinite(self.worker_poll_s) or self.worker_poll_s <= 0:
            raise ConfigError(f"invalid worker_poll_s: {self.worker_poll_s} (must be finite > 0)")

        if not math.isfinite(self.inbox_poll_interval_s) or self.inbox_poll_interval_s <= 0:
            raise ConfigError(f"invalid inbox_poll_interval_s: {self.inbox_poll_interval_s} (must be finite > 0)")

        if not math.isfinite(self.schedule_interval_s) or self.schedule_interval_s <= 0:
            raise ConfigError(f"invalid schedule_interval_s: {self.schedule_interval_s} (must be finite > 0)")

        if self.idle_quota <= 0:
            raise ConfigError(f"invalid idle_quota: {self.idle_quota} (must be > 0)")

        if not math.isfinite(self.idle_max_duration_s) or self.idle_max_duration_s <= 0:
            raise ConfigError(f"invalid idle_max_duration_s: {self.idle_max_duration_s} (must be finite > 0)")

        if not math.isfinite(self.idle_backoff_base_s) or self.idle_backoff_base_s <= 0:
            raise ConfigError(f"invalid idle_backoff_base_s: {self.idle_backoff_base_s} (must be finite > 0)")

        if not math.isfinite(self.idle_backoff_max_s) or self.idle_backoff_max_s < self.idle_backoff_base_s:
            raise ConfigError(
                f"invalid idle_backoff_max_s: {self.idle_backoff_max_s} (must be finite and >= idle_backoff_base_s)"
            )

        if not math.isfinite(self.idle_hysteresis_s) or self.idle_hysteresis_s < 0:
            raise ConfigError(f"invalid idle_hysteresis_s: {self.idle_hysteresis_s} (must be finite >= 0)")

        if not math.isfinite(self.folder_patrol_interval_s) or self.folder_patrol_interval_s <= 0:
            raise ConfigError(
                f"invalid folder_patrol_interval_s: {self.folder_patrol_interval_s} (must be finite > 0)"
            )

        if self.folder_patrol_max_probes <= 0:
            raise ConfigError(f"invalid folder_patrol_max_probes: {self.folder_patrol_max_probes} (must be > 0)")

        if (
            not math.isfinite(self.folder_patrol_max_unprobed_s)
            or self.folder_patrol_max_unprobed_s < self.folder_patrol_interval_s
        ):
            raise ConfigError(
                f"invalid folder_patrol_max_unprobed_s: {self.folder_patrol_max_unprobed_s} "
                "(must be finite and >= folder_patrol_interval_s)"
            )
