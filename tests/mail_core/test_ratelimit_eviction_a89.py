"""A89: capacity eviction must not full-scan the failure map per new key.

Pre-fix, ``_evict_to_capacity`` pruned *every* tracked key and then ran
``min()`` over the whole map inside the limiter lock, so a key spray
turned each new key into an O(n) scan under lock. Eviction is now by
insertion order (front of the map first): expired entries sitting at
the front are pruned away (each key is pruned/removed at most once, so
this stays amortized O(1)), then the oldest-inserted live keys are
evicted until there is room. The capacity bound and per-key semantics
are unchanged.
"""

from __future__ import annotations

from mail_core.security.ratelimit import LoginRateLimiter


def test_eviction_follows_insertion_order_not_last_activity():
    limiter = LoginRateLimiter(max_failures=5, window_s=300.0, max_keys=10)
    for i in range(10):
        limiter.record_failure(f"k{i}", now=1_000.0)
    # k0 has the most recent activity but is the oldest-inserted key.
    limiter.record_failure("k0", now=1_001.0)
    limiter.record_failure("fresh", now=1_002.0)
    assert "k0" not in limiter._fails
    assert "k1" in limiter._fails
    assert "fresh" in limiter._fails
    assert len(limiter._fails) <= 10


def test_new_key_at_capacity_does_not_prune_every_key(monkeypatch):
    limiter = LoginRateLimiter(max_failures=5, window_s=300.0, max_keys=10)
    for i in range(10):
        limiter.record_failure(f"k{i}", now=1_000.0)

    calls = 0
    original_prune = LoginRateLimiter._prune

    def counting_prune(self, key, now):
        nonlocal calls
        calls += 1
        return original_prune(self, key, now)

    monkeypatch.setattr(LoginRateLimiter, "_prune", counting_prune)
    limiter.record_failure("fresh", now=1_001.0)
    # Front-key prune + the new key's own prune; never one prune per key.
    assert calls <= 3


def test_expired_front_entries_free_room_without_evicting_live_keys():
    limiter = LoginRateLimiter(max_failures=5, window_s=10.0, max_keys=3)
    limiter.record_failure("expired", now=0.0)
    limiter.record_failure("live1", now=100.0)
    limiter.record_failure("live2", now=100.0)
    limiter.record_failure("fresh", now=100.0)
    assert "expired" not in limiter._fails
    assert "live1" in limiter._fails
    assert "live2" in limiter._fails
    assert "fresh" in limiter._fails
