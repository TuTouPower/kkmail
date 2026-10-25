"""In-process failed-login limiter (per client address, sliding window).

Keyed on the socket peer (``request.client.host``) — never on X-Forwarded-For,
which a client can forge. Behind a reverse proxy, run uvicorn with
``--proxy-headers --forwarded-allow-ips=<proxy>`` so the peer is the real client.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque


class LoginRateLimiter:
    def __init__(self, *, max_failures: int, window_s: float) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
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
    max_failures=int(os.environ.get("MAIL_CORE_LOGIN_MAX_FAILURES") or 10),
    window_s=float(os.environ.get("MAIL_CORE_LOGIN_WINDOW_S") or 300),
)
