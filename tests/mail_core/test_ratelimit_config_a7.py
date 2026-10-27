"""A7: login limiter env parsing must never break import or index q[0].

Pre-fix, the module-level ``login_limiter`` parsed MAIL_CORE_LOGIN_*
with bare int()/float() at import time (a typo crashed the process),
and max_failures=0/negative made ``retry_after`` evaluate ``q[0]`` on
an empty deque (IndexError -> login 500). Construction now clamps to
max_failures>=1 and a finite positive window, and env parsing follows
the worker's _positive_float_setting pattern: invalid values warn and
fall back to defaults.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from mail_core.security import ratelimit
from mail_core.security.ratelimit import LoginRateLimiter


def test_zero_max_failures_is_clamped_and_retry_after_never_indexes_empty_deque():
    limiter = LoginRateLimiter(max_failures=0, window_s=300.0)
    assert limiter.max_failures >= 1
    # Unknown key: allowed immediately, no IndexError.
    assert limiter.retry_after("203.0.113.1", now=100.0) == 0
    limiter.record_failure("203.0.113.1", now=100.0)
    assert limiter.retry_after("203.0.113.1", now=101.0) > 0


def test_negative_max_failures_is_clamped():
    limiter = LoginRateLimiter(max_failures=-3, window_s=300.0)
    assert limiter.max_failures >= 1
    assert limiter.retry_after("203.0.113.2", now=0.0) == 0


@pytest.mark.parametrize("bad_window", [0.0, -5.0, float("nan"), float("inf")])
def test_non_positive_or_non_finite_window_falls_back(bad_window):
    limiter = LoginRateLimiter(max_failures=5, window_s=bad_window)
    assert limiter.window_s > 0
    assert limiter.window_s == limiter.window_s  # not NaN
    assert limiter.window_s != float("inf")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", 10), ("-4", 10), ("abc", 10), ("", 10), ("7", 7)],
)
def test_max_failures_env_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("MAIL_CORE_LOGIN_MAX_FAILURES", raw)
    assert ratelimit._positive_int_setting("MAIL_CORE_LOGIN_MAX_FAILURES", 10) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0", 300.0), ("-1.5", 300.0), ("abc", 300.0), ("nan", 300.0), ("inf", 300.0), ("60", 60.0)],
)
def test_window_env_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("MAIL_CORE_LOGIN_WINDOW_S", raw)
    assert ratelimit._positive_float_setting("MAIL_CORE_LOGIN_WINDOW_S", 300.0) == expected


def test_module_imports_with_garbage_login_env():
    """Import-time env garbage must not crash the process (login 500 / no boot)."""
    env = dict(os.environ)
    env["PYTHONPATH"] = "src"
    env["MAIL_CORE_LOGIN_MAX_FAILURES"] = "abc"
    env["MAIL_CORE_LOGIN_WINDOW_S"] = "nan"
    env["MAIL_CORE_LOGIN_MAX_KEYS"] = "0"
    proc = subprocess.run(
        [sys.executable, "-c", "from mail_core.security.ratelimit import login_limiter; "
         "assert login_limiter.max_failures >= 1 and login_limiter.window_s > 0"],
        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
