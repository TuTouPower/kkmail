"""A379: the SSE live-tail wait must not busy-loop near the epoch recheck.

Pre-fix, the queue wait timeout was
``min(15.0, max(0.0, next_epoch_recheck - now))``: as the recheck
point approached, the timeout shrank toward zero, ``wait_for`` timed
out instantly, and the keepalive branch looped at full speed until
the recheck fired. The timeout now has a 1s floor (the recheck still
runs at the top of the next loop iteration, at most ~1s late), while
the 15s keepalive cap and the no-session behaviour are unchanged.
"""

from __future__ import annotations


def _timeout(next_recheck, now):
    from mail_core.api.sse import _stream_wait_timeout_s

    return _stream_wait_timeout_s(next_recheck, now)


def test_no_session_epoch_waits_full_keepalive_interval():
    assert _timeout(None, 1_000.0) == 15.0


def test_distant_recheck_is_capped_at_keepalive_interval():
    assert _timeout(1_120.0, 1_000.0) == 15.0


def test_recheck_a_few_seconds_out_shortens_the_wait():
    assert _timeout(1_005.0, 1_000.0) == 5.0


def test_imminent_recheck_hits_the_one_second_floor():
    assert _timeout(1_000.05, 1_000.0) == 1.0


def test_overdue_recheck_still_waits_the_floor_not_zero():
    assert _timeout(999.0, 1_000.0) == 1.0
