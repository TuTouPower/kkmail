"""Worker heartbeat persistence and status checks."""

from __future__ import annotations

import json
import logging
import os
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from mail_core.mail.storage.models import AppSetting

log = logging.getLogger("mail_core.worker.heartbeat")

HEARTBEAT_PREFIX = "worker:heartbeat:"
DEFAULT_STALE_AFTER_SECONDS = 60.0


def _heartbeat_key(worker_id: str) -> str:
    return f"{HEARTBEAT_PREFIX}{worker_id}"


def record_heartbeat(
    session: Session,
    worker_id: str,
    *,
    active_jobs: int = 0,
    extra: dict[str, Any] | None = None,
) -> None:
    """Record current worker heartbeat timestamp into AppSetting."""
    key = _heartbeat_key(worker_id)
    now = datetime.now(timezone.utc)
    payload = {
        "worker_id": worker_id,
        "updated_at": now.isoformat(),
        "pid": os.getpid(),
        "active_jobs": active_jobs,
    }
    if extra:
        payload.update(extra)

    row = session.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=json.dumps(payload, sort_keys=True))
        session.add(row)
    else:
        row.value = json.dumps(payload, sort_keys=True)
    session.flush()


def get_worker_heartbeats(
    session: Session,
    *,
    stale_after_seconds: float = DEFAULT_STALE_AFTER_SECONDS,
) -> tuple[bool, float | None, list[dict[str, Any]]]:
    """Retrieve active worker heartbeats.

    Returns:
        (is_healthy, min_lag_seconds, active_workers)
    """
    rows = session.scalars(
        select(AppSetting).where(AppSetting.key.like(f"{HEARTBEAT_PREFIX}%"))
    ).all()

    now = datetime.now(timezone.utc)
    active_workers: list[dict[str, Any]] = []
    min_lag: float | None = None

    for row in rows:
        try:
            data = json.loads(row.value)
            raw_ts = data.get("updated_at")
            if not raw_ts:
                continue
            updated_at = datetime.fromisoformat(raw_ts)
            lag = (now - updated_at).total_seconds()
            if lag < 0:
                lag = 0.0
            is_active = lag <= stale_after_seconds
            data["lag_seconds"] = round(lag, 2)
            data["active"] = is_active
            if is_active:
                active_workers.append(data)
                if min_lag is None or lag < min_lag:
                    min_lag = lag
        except Exception:
            continue

    is_healthy = len(active_workers) > 0
    return is_healthy, (round(min_lag, 2) if min_lag is not None else None), active_workers


def cleanup_stale_heartbeats(
    session: Session,
    *,
    older_than_seconds: float = 86400.0,
) -> int:
    """Remove heartbeat entries older than retention threshold."""
    rows = session.scalars(
        select(AppSetting).where(AppSetting.key.like(f"{HEARTBEAT_PREFIX}%"))
    ).all()
    now = datetime.now(timezone.utc)
    keys_to_delete: list[str] = []
    for row in rows:
        try:
            data = json.loads(row.value)
            raw_ts = data.get("updated_at")
            if not raw_ts:
                keys_to_delete.append(row.key)
                continue
            updated_at = datetime.fromisoformat(raw_ts)
            if (now - updated_at).total_seconds() > older_than_seconds:
                keys_to_delete.append(row.key)
        except Exception:
            keys_to_delete.append(row.key)

    if keys_to_delete:
        session.execute(
            delete(AppSetting).where(AppSetting.key.in_(keys_to_delete))
        )
        session.flush()
    return len(keys_to_delete)


class WorkerHeartbeatLoop:
    """Independent background thread for worker process health heartbeats."""

    def __init__(
        self,
        worker_id: str,
        session_factory: Callable[[], Session],
        *,
        interval_s: float = 15.0,
    ) -> None:
        self.worker_id = worker_id
        self.session_factory = session_factory
        self.interval_s = max(interval_s, 0.01)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._active_jobs = 0
        self._lock = threading.Lock()

    def set_active_jobs(self, count: int) -> None:
        with self._lock:
            self._active_jobs = max(count, 0)

    def get_active_jobs(self) -> int:
        with self._lock:
            return self._active_jobs

    def _tick(self) -> None:
        try:
            with self.session_factory() as session:
                record_heartbeat(
                    session,
                    worker_id=self.worker_id,
                    active_jobs=self.get_active_jobs(),
                )
                session.commit()
        except Exception as exc:
            from mail_core.security.redact import safe_error

            log.warning("worker heartbeat write failed: %s", safe_error(exc))

    def start(self) -> None:
        self._tick()
        self._stop_event.clear()

        def _loop() -> None:
            while not self._stop_event.is_set():
                if self._stop_event.wait(timeout=self.interval_s):
                    break
                self._tick()

        self._thread = threading.Thread(
            target=_loop,
            name=f"worker-heartbeat-{self.worker_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            self._thread = None
