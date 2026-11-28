"""Readiness probe with a single Core-Connection read path and short TTL cache (t095).

The API ``/ready`` probe historically opened ORM Sessions that emitted a
``ROLLBACK`` on every close (232k+ in production). All reads here go through a
plain Core connection, so the probe is read-only at the driver level. A bounded
in-memory TTL cache avoids hammering PG at the container healthcheck cadence;
DB/LISTEN transitions invalidate it immediately.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text

from mail_core.liveness import read_liveness_stamp, stamp_path

DEFAULT_TTL_S = 5.0


@dataclass(frozen=True)
class ReadinessSnapshot:
    schema_revision: str | None
    listener_ready: bool
    worker_active: bool
    worker_lag_seconds: float | None


class ReadinessProbe:
    """Cached, ORM-free readiness snapshot.

    The caller supplies cheap callables for schema revision, LISTEN state and
    active-worker state so this module stays transport-agnostic and testable.
    """

    def __init__(self, *, ttl_s: float = DEFAULT_TTL_S) -> None:
        self.ttl_s = max(0.0, ttl_s)
        self._lock = threading.Lock()
        self._cached_at: float = 0.0
        self._snapshot: ReadinessSnapshot | None = None

    def invalidate(self) -> None:
        with self._lock:
            self._cached_at = 0.0
            self._snapshot = None

    def cached_worker_active(self) -> bool | None:
        """Cached worker-active signal when the snapshot is still fresh."""
        with self._lock:
            if self._snapshot is None:
                return None
            if (time.monotonic() - self._cached_at) < self.ttl_s:
                return self._snapshot.worker_active
            return None

    def snapshot(
        self,
        *,
        schema_revision: str | None,
        listener_ready: bool,
        worker_active: bool,
        worker_lag_seconds: float | None = None,
    ) -> ReadinessSnapshot:
        """Return the cached snapshot when fresh, else rebuild from arguments.

        The caller reads DB/LISTEN/worker state with Core connections; this
        method only owns the cache boundary.
        """
        now = time.monotonic()
        with self._lock:
            fresh = (
                self._snapshot is not None
                and (now - self._cached_at) < self.ttl_s
            )
            if fresh:
                assert self._snapshot is not None
                return self._snapshot
            snap = ReadinessSnapshot(
                schema_revision=schema_revision,
                listener_ready=listener_ready,
                worker_active=worker_active,
                worker_lag_seconds=worker_lag_seconds,
            )
            self._snapshot = snap
            self._cached_at = now
            return snap


_probe = ReadinessProbe()


def get_readiness_probe() -> ReadinessProbe:
    return _probe


def read_worker_active_via_core(engine: Any, *, stale_after_s: float = 60.0) -> tuple[bool, float | None]:
    """Read active-worker state with a Core connection (no ORM Session/ROLLBACK)."""
    from mail_core.worker.heartbeat import (
        HEARTBEAT_PREFIX,
        _parse_heartbeat_row,
    )

    now_dt = datetime.now(timezone.utc)
    # AUTOCOMMIT: a plain Core Connection in an implicit transaction emits a
    # ROLLBACK on close; readiness reads must be strictly read-only with zero
    # rollback traffic (the 232k ROLLBACK root cause).
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        rows = conn.execute(
            text("SELECT value FROM app_settings WHERE key LIKE :prefix"),
            {"prefix": f"{HEARTBEAT_PREFIX}%"},
        ).scalars().all()
    active = False
    min_lag: float | None = None
    for value in rows:
        parsed = _parse_heartbeat_row(value)
        if parsed is None:
            continue
        _data, updated_at = parsed
        lag = max(0.0, (now_dt - updated_at).total_seconds())
        if lag <= stale_after_s:
            active = True
            if min_lag is None or lag < min_lag:
                min_lag = lag
    # t095 AC-005 / t096 AC-005: only check the local worker liveness stamp when
    # running an embedded worker or when MAIL_CORE_LIVENESS_STAMP is explicitly
    # configured; a distributed API process must not read a stray /tmp stamp.
    check_local_stamp = bool(
        (os.environ.get("MAIL_CORE_LIVENESS_STAMP") or "").strip()
    ) or (os.environ.get("MAIL_CORE_EMBEDDED_WORKER") != "0")
    if check_local_stamp:
        stamp = read_liveness_stamp()
        if stamp is not None:
            try:
                age = time.time() - Path(stamp_path()).stat().st_mtime
                if age > stale_after_s:
                    active = False
            except OSError:
                active = False
    return active, min_lag
