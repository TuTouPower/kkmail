"""In-process failed-login limiter keyed by the verified request client address.

When ``MAIL_CORE_FORWARDED_ALLOW_IPS`` configures trusted proxies, the API's
``ProxyHeadersMiddleware`` rewrites ``request.client.host`` to the forwarded
client address. Never read ``X-Forwarded-For`` directly; untrusted clients can
forge it.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections import deque

log = logging.getLogger("mail_core.security.ratelimit")

_DEFAULT_MAX_FAILURES = 10
_DEFAULT_WINDOW_S = 300.0
_DEFAULT_MAX_KEYS = 10_000


def _positive_int_setting(name: str, default: int) -> int:
    """Parse an env int like worker.main._positive_float_setting: warn + default."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        log.warning("invalid numeric environment setting %s=%r; using default %s", name, raw, default)
        return default
    return value


def _positive_float_setting(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        value = math.nan
    if not math.isfinite(value) or value <= 0:
        log.warning("invalid numeric environment setting %s=%r; using default %s", name, raw, default)
        return default
    return value


class LoginRateLimiter:
    def __init__(self, *, max_failures: int, window_s: float, max_keys: int = 10_000) -> None:
        # Clamp defensively (A7): max_failures < 1 would make retry_after
        # index q[0] on an empty deque, and a non-finite/non-positive
        # window breaks the retry_after arithmetic.
        max_failures = int(max_failures)
        if max_failures < 1:
            log.warning("invalid max_failures=%r; clamping to 1", max_failures)
            max_failures = 1
        window_s = float(window_s)
        if not math.isfinite(window_s) or window_s <= 0:
            log.warning("invalid window_s=%r; using default %s", window_s, _DEFAULT_WINDOW_S)
            window_s = _DEFAULT_WINDOW_S
        self.max_failures = max_failures
        self.window_s = window_s
        # Global bound on tracked keys (B5a): per-key pruning alone never
        # shrinks the map for keys that are never touched again, so a
        # spray of distinct source addresses grew it without limit.
        self.max_keys = max(1, int(max_keys))
        self._fails: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._fails.get(key)
        if q is None:
            return deque()
        while q and now - q[0] > self.window_s:
            q.popleft()
        if not q:
            self._fails.pop(key, None)
        return q

    def _evict_to_capacity(self, now: float) -> None:
        """Make room for one new key: expired entries first, then oldest."""
        if len(self._fails) < self.max_keys:
            return
        for key in list(self._fails):
            self._prune(key, now)
        while len(self._fails) >= self.max_keys:
            oldest = min(self._fails, key=lambda k: self._fails[k][-1])
            self._fails.pop(oldest, None)

    def retry_after(self, key: str, now: float | None = None) -> int:
        """Seconds until another attempt is allowed (0 = allowed now)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            q = self._prune(key, now)
            if len(q) < self.max_failures:
                return 0
            return max(1, int(self.window_s - (now - q[0])) + 1)

    def record_failure(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            if key not in self._fails:
                self._evict_to_capacity(now)
            q = self._prune(key, now)
            q.append(now)
            self._fails[key] = q

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._fails.clear()
            else:
                self._fails.pop(key, None)


login_limiter = LoginRateLimiter(
    max_failures=_positive_int_setting("MAIL_CORE_LOGIN_MAX_FAILURES", _DEFAULT_MAX_FAILURES),
    window_s=_positive_float_setting("MAIL_CORE_LOGIN_WINDOW_S", _DEFAULT_WINDOW_S),
    max_keys=_positive_int_setting("MAIL_CORE_LOGIN_MAX_KEYS", _DEFAULT_MAX_KEYS),
)
