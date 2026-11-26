"""Bounded per-endpoint negative-dial circuit breaker and half-open bulkhead.

Prevents repeatedly blocked remote endpoints (e.g., GFW-dropped IMAP servers)
from consuming global connection slots on every concurrent account retry.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

EndpointKey = tuple[str, str, int]


class EndpointCircuitOpenError(ConnectionError):
    """Raised immediately when an endpoint's connect circuit is cooling down."""

    def __init__(
        self,
        message: str,
        *,
        endpoint: EndpointKey,
        retry_after_s: float,
    ) -> None:
        super().__init__(message)
        self.endpoint = endpoint
        self.retry_after_s = max(0.0, float(retry_after_s))

    @property
    def retry_after_seconds(self) -> float:
        """Scheduler-compatible deferral interval matching CAPACITY_ERRORS contract."""
        return self.retry_after_s


@dataclass(slots=True)
class _EndpointEntry:
    consecutive_failures: int = 0
    open_until: float = 0.0
    half_open_probing: bool = False
    last_touched: float = 0.0


class EndpointBulkhead:
    """Thread-safe connect-phase circuit breaker keyed by (proxy_key, host, port)."""

    def __init__(
        self,
        *,
        failure_threshold: int = 2,
        cooldown_s: float = 30.0,
        max_endpoints: int = 1024,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if cooldown_s < 0:
            raise ValueError("cooldown_s must be >= 0")
        self.failure_threshold = int(failure_threshold)
        self.cooldown_s = float(cooldown_s)
        self.max_endpoints = int(max_endpoints)
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._entries: dict[EndpointKey, _EndpointEntry] = {}

    def _prune_if_needed(self, now: float) -> None:
        if len(self._entries) < self.max_endpoints:
            return
        expired = [
            key
            for key, entry in self._entries.items()
            if not entry.half_open_probing and entry.open_until <= now and entry.consecutive_failures == 0
        ]
        for key in expired:
            del self._entries[key]
        if len(self._entries) >= self.max_endpoints:
            oldest = min(self._entries.items(), key=lambda kv: kv[1].last_touched)[0]
            del self._entries[oldest]

    def raise_if_open(self, key: EndpointKey) -> None:
        """Read-only fast-fail check suitable BEFORE acquiring external permits.

        Raises :class:`EndpointCircuitOpenError` when ``key`` is inside its
        cooldown window OR another caller is already running the half-open
        probe. Never mutates half-open probe ownership.
        """
        if self.cooldown_s <= 0:
            return
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            if now < entry.open_until:
                retry_after = entry.open_until - now
                raise EndpointCircuitOpenError(
                    f"endpoint circuit open for {key[1]}:{key[2]} via {key[0]} (retry in {retry_after:.1f}s)",
                    endpoint=key,
                    retry_after_s=retry_after,
                )
            if entry.open_until > 0.0 and entry.half_open_probing:
                raise EndpointCircuitOpenError(
                    f"endpoint half-open probe already active for {key[1]}:{key[2]} via {key[0]}",
                    endpoint=key,
                    retry_after_s=1.0,
                )

    def before_dial(self, key: EndpointKey) -> None:
        """Check whether a dial attempt to ``key`` may proceed, or fail fast."""
        if self.cooldown_s <= 0:
            return
        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            entry.last_touched = now
            if now < entry.open_until:
                retry_after = entry.open_until - now
                raise EndpointCircuitOpenError(
                    f"endpoint circuit open for {key[1]}:{key[2]} via {key[0]} (retry in {retry_after:.1f}s)",
                    endpoint=key,
                    retry_after_s=retry_after,
                )
            if entry.open_until > 0.0:
                # Cooldown elapsed: allow strictly one concurrent half-open probe
                # so concurrent callers cannot stampede a blocked endpoint.
                if entry.half_open_probing:
                    raise EndpointCircuitOpenError(
                        f"endpoint half-open probe already active for {key[1]}:{key[2]} via {key[0]}",
                        endpoint=key,
                        retry_after_s=1.0,
                    )
                entry.half_open_probing = True

    def record_success(self, key: EndpointKey) -> None:
        """Close the circuit on successful connect + handshake."""
        with self._lock:
            self._entries.pop(key, None)

    def record_transport_failure(self, key: EndpointKey) -> None:
        """Record a connect-phase transport failure; open circuit on threshold or probe failure."""
        if self.cooldown_s <= 0:
            return
        now = self._clock()
        with self._lock:
            self._prune_if_needed(now)
            entry = self._entries.get(key)
            if entry is None:
                entry = _EndpointEntry(last_touched=now)
                self._entries[key] = entry
            was_probing = entry.half_open_probing
            entry.half_open_probing = False
            entry.consecutive_failures += 1
            entry.last_touched = now
            if was_probing or entry.consecutive_failures >= self.failure_threshold:
                entry.open_until = now + self.cooldown_s

    def release_probe_without_outcome(self, key: EndpointKey) -> None:
        """Release a half-open probe claim when aborted before transport result."""
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                entry.half_open_probing = False

    def snapshot(self) -> dict[EndpointKey, dict[str, Any]]:
        """Return diagnostic circuit state per tracked endpoint."""
        now = self._clock()
        with self._lock:
            result: dict[EndpointKey, dict[str, Any]] = {}
            for key, entry in self._entries.items():
                state = "closed"
                if entry.half_open_probing:
                    state = "half_open"
                elif now < entry.open_until:
                    state = "open"
                result[key] = {
                    "state": state,
                    "consecutive_failures": entry.consecutive_failures,
                    "retry_after_s": max(0.0, entry.open_until - now),
                }
            return result

    def reset(self) -> None:
        """Clear all tracked endpoint circuits (primarily for tests)."""
        with self._lock:
            self._entries.clear()


_DEFAULT_BULKHEAD = EndpointBulkhead()


def default_bulkhead() -> EndpointBulkhead:
    """Return the process-wide shared outbound endpoint bulkhead."""
    return _DEFAULT_BULKHEAD


def configure_default_bulkhead(*, failure_threshold: int | None = None, cooldown_s: float | None = None) -> EndpointBulkhead:
    """Reconfigure thresholds on the shared default bulkhead in-place."""
    global _DEFAULT_BULKHEAD
    with _DEFAULT_BULKHEAD._lock:
        if failure_threshold is not None:
            if int(failure_threshold) < 1:
                raise ValueError("failure_threshold must be >= 1")
            _DEFAULT_BULKHEAD.failure_threshold = int(failure_threshold)
        if cooldown_s is not None:
            if float(cooldown_s) < 0:
                raise ValueError("cooldown_s must be >= 0")
            _DEFAULT_BULKHEAD.cooldown_s = float(cooldown_s)
    return _DEFAULT_BULKHEAD
