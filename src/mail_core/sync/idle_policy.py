"""Pure IDLE seat policy: no I/O, no database, no threads.

Everything in this module is a deterministic function of its inputs
(the only nondeterminism is the optional backoff jitter, injectable
for tests). The watcher runtime (``idle_watcher``) loads candidates
from the database, asks this module who should hold seats, and drives
the per-account sessions; policy never reaches back into the runtime.

Seat ranking is purely by mail data — the newest server arrival time
(IMAP INTERNALDATE, stored as ``Message.sort_time``) in the account's
inbox — with hysteresis so borderline accounts do not churn
connections. Accounts whose inbox is empty rank below every account
holding mail, ordered among themselves by their other folders' newest
arrival, then by account creation time. The ranking signal
deliberately comes from the messages themselves, never from sync
bookkeeping timestamps (a checkpoint's ``updated_at`` is written by
the sync machinery itself and would be self-confirming).
"""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mail_core import runtime_budget


@dataclass(frozen=True)
class IdleWatcherConfig:
    enabled: bool = True
    quota: int = runtime_budget.DEFAULT_IDLE_QUOTA
    max_duration_s: float = 1680.0
    backoff_base_s: float = 5.0
    backoff_max_s: float = 300.0
    hysteresis_s: float = 300.0
    reconcile_interval_s: float = 15.0
    close_timeout_s: float = 5.0

    @classmethod
    def from_app_config(cls, cfg: Any) -> "IdleWatcherConfig":
        return cls(
            enabled=bool(cfg.idle_enabled),
            quota=int(cfg.idle_quota),
            max_duration_s=float(cfg.idle_max_duration_s),
            backoff_base_s=float(cfg.idle_backoff_base_s),
            backoff_max_s=float(cfg.idle_backoff_max_s),
            hysteresis_s=float(cfg.idle_hysteresis_s),
        )


@dataclass(frozen=True)
class IdleCandidate:
    """One eligible account plus the mail-data keys seats are ranked by.

    All timestamps are server arrival times (IMAP INTERNALDATE as
    stored on ``Message.sort_time``) — never sender ``Date`` headers
    and never sync bookkeeping timestamps.
    """

    account_id: uuid.UUID
    folder_id: uuid.UUID
    # Newest arrival among messages currently located in the inbox;
    # None when no located message carries an arrival timestamp.
    inbox_latest_arrival_at: datetime | None
    # True when the inbox currently holds at least one message (even
    # if every arrival timestamp is NULL): an account holding mail
    # always outranks an account whose inbox is empty.
    inbox_has_messages: bool
    # Newest arrival among messages in the account's other folders.
    other_latest_arrival_at: datetime | None
    account_created_at: datetime
    credential_fingerprint: str


def backoff_delay(attempt: int, config: IdleWatcherConfig, *, jitter_fraction: float | None = None) -> float:
    """Exponential backoff with up to +100% jitter (AC-003 spreading)."""
    base = min(config.backoff_max_s, config.backoff_base_s * (2**attempt))
    fraction = random.random() if jitter_fraction is None else jitter_fraction
    return base * (1.0 + fraction)


def _epoch(value: datetime | None) -> float:
    return value.timestamp() if value is not None else float("-inf")


def seat_group(candidate: IdleCandidate) -> int:
    """0 = inbox holds mail (main group), 1 = inbox empty."""
    return 0 if candidate.inbox_has_messages else 1


def primary_arrival(candidate: IdleCandidate) -> datetime | None:
    """The comparable arrival key within a candidate's seat group."""
    if candidate.inbox_has_messages:
        return candidate.inbox_latest_arrival_at
    return candidate.other_latest_arrival_at


def rank_key(candidate: IdleCandidate) -> tuple:
    """Total seat order, hottest first:

    1. accounts whose inbox holds mail, before empty-inbox accounts;
    2. within a group, the group's primary arrival time, newest first
       (inbox arrivals for the main group, other-folder arrivals for
       the empty-inbox group; a missing timestamp sorts last);
    3. other-folder newest arrival, newest first;
    4. account creation time, newest first;
    5. account id, ascending (stable final tie-break).
    """
    return (
        seat_group(candidate),
        -_epoch(primary_arrival(candidate)),
        -_epoch(candidate.other_latest_arrival_at),
        -candidate.account_created_at.timestamp(),
        str(candidate.account_id),
    )


def challenger_advantage_s(challenger: IdleCandidate, incumbent: IdleCandidate) -> float:
    """How much hotter a challenger is than an incumbent, in seconds.

    Only defined within one seat group on comparable primary keys:
    a challenger from the hotter group wins categorically (infinite
    advantage, hysteresis never rescues across groups); when either
    primary key is missing there is nothing comparable, so the
    advantage is 0 and the incumbent is kept (stable order, no churn).
    """
    if seat_group(challenger) != seat_group(incumbent):
        return float("inf")
    challenger_key = primary_arrival(challenger)
    incumbent_key = primary_arrival(incumbent)
    if challenger_key is None or incumbent_key is None:
        return 0.0
    return (challenger_key - incumbent_key).total_seconds()


def select_idle_holders(
    candidates: list[IdleCandidate],
    *,
    current_holders: set[uuid.UUID],
    quota: int,
    hysteresis_s: float,
    now: datetime,
) -> set[uuid.UUID]:
    """Choose which accounts hold IDLE seats.

    Top-``quota`` by the seat order in ``rank_key`` wins; an incumbent
    outside the top set keeps its seat unless the weakest challenger's
    advantage on the comparable arrival key exceeds ``hysteresis_s``
    — this prevents connection churn when two accounts' newest mail
    arrived at near-identical times.
    """
    ranked = sorted(candidates, key=rank_key)
    by_id = {c.account_id: c for c in ranked}
    rank_pos = {c.account_id: pos for pos, c in enumerate(ranked)}
    selected: set[uuid.UUID] = {c.account_id for c in ranked[:quota]}

    for incumbent in ranked:
        if incumbent.account_id not in current_holders or incumbent.account_id in selected:
            continue
        challengers = [aid for aid in selected if aid not in current_holders]
        if not challengers:
            break
        weakest = max(challengers, key=lambda aid: rank_pos[aid])
        advantage = challenger_advantage_s(by_id[weakest], incumbent)
        if advantage <= hysteresis_s:
            selected.discard(weakest)
            selected.add(incumbent.account_id)
    return selected
