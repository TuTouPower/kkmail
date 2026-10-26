"""B5a: the login rate limiter's failure map must be globally bounded.

Pre-fix, ``_fails`` only pruned the key being touched; entries for keys
never seen again accumulated forever, so spraying login attempts from
many distinct source addresses grew the in-process map without limit.
The limiter now caps tracked keys (expired entries evicted first, then
the least-recently-active), while per-key semantics are unchanged.
"""

from __future__ import annotations

from mail_core.security.ratelimit import LoginRateLimiter


def test_random_key_spray_never_exceeds_capacity():
    limiter = LoginRateLimiter(max_failures=5, window_s=300.0, max_keys=100)
    for i in range(500):
        limiter.record_failure(f"198.51.100.{i}", now=1_000.0 + i)
    assert len(limiter._fails) <= 100
    # The most recent keys are the ones retained.
    assert "198.51.100.499" in limiter._fails
    assert "198.51.100.450" in limiter._fails
    assert "198.51.100.0" not in limiter._fails


def test_expired_entries_are_evicted_before_live_ones():
    limiter = LoginRateLimiter(max_failures=5, window_s=10.0, max_keys=50)
    for i in range(50):
        limiter.record_failure(f"old-{i}", now=0.0)
    # At t=100 every old entry is expired; a fresh key must evict the
    # expired ones (all of them), not squeeze out anything live.
    limiter.record_failure("fresh", now=100.0)
    assert list(limiter._fails) == ["fresh"]


def test_per_key_limit_semantics_unchanged_at_capacity():
    limiter = LoginRateLimiter(max_failures=3, window_s=60.0, max_keys=10)
    for i in range(20):
        limiter.record_failure(f"other-{i}", now=500.0 + i)
    for j in range(3):
        limiter.record_failure("victim", now=600.0 + j)
    assert limiter.retry_after("victim", now=601.0) > 0
    assert limiter.retry_after("never-seen", now=601.0) == 0
    limiter.reset("victim")
    assert limiter.retry_after("victim", now=601.0) == 0
