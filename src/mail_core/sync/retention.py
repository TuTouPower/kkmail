"""Transient queue retention contract (t094 AC-003 / AC-007).

Both queues are transport buffers, not audit archives. Their windows are short,
fixed, and expressed in code (no product-level env switch). SSE replay and
sync-request settlement have their own authoritative watermarks, so a client
that falls behind the window must resync rather than expect history.
"""

from __future__ import annotations

from datetime import timedelta

# Completed-worker and published-outbox rows are retained only long enough to
# cover SSE reconnection / in-flight dispatch. Reduced from the historical 7d.
COMPLETED_JOB_RETENTION = timedelta(hours=24)
PUBLISHED_OUTBOX_RETENTION = timedelta(hours=24)

# Batch caps bound the write cost of a single prune sweep. A backlog larger
# than the cap drains across repeated 60s sweeps; the steady-state observation
# is "terminal rows older than the window trend to zero across sweeps".
COMPLETED_JOB_PRUNE_BATCH = 5000
PUBLISHED_OUTBOX_PRUNE_BATCH = 5000

# A prune that removed fewer than this many rows is treated as steady-state
# housekeeping and does not trigger statistics refresh.
STATS_REFRESH_MIN_DELETED = 1000

STATS_REFRESH_TABLES = ("worker_jobs", "outbox")

# t094 AC-006: message tables accumulated stale statistics (n_live_tup=68 vs
# 22,095 real rows) after bulk import. Each table is compared against its own
# real row count; reltuples within this relative error is acceptable. A bulk
# sync of at least this many changed rows triggers one refresh, capped by a
# min-interval so short deltas never re-ANALYZE.
MESSAGE_STATS_TABLES = ("message_search", "messages", "message_bodies")
MESSAGE_STATS_BULK_CHANGED_ROWS = 1000
MESSAGE_STATS_RELTUPLES_REL_ERROR = 0.25
MESSAGE_STATS_MIN_INTERVAL_S = 300.0


def refresh_table_stats_if_bulk(deleted: int, table: str) -> bool:
    """Return whether a bulk prune is large enough to warrant ANALYZE.

    Kept as a pure predicate so the threshold is testable without a live DB.
    Callers run ``ANALYZE <table>`` only when this is True; small routine
    deletions (short delta churn) never pay the refresh cost.
    """
    return deleted >= STATS_REFRESH_MIN_DELETED and table in STATS_REFRESH_TABLES


def is_bulk_message_sync(changed_rows: int) -> bool:
    """Whether a delta sync changed enough rows to refresh message-table stats."""
    return changed_rows >= MESSAGE_STATS_BULK_CHANGED_ROWS


def reltuples_within_tolerance(reltuples: float, real_rows: int) -> bool:
    """Whether ANALYZE's estimate is within the declared relative error bound.

    Each message table is judged against its own real row count; a stale
    estimate (e.g. n_live_tup=68 for 22,095 rows) fails. ``real_rows == 0`` is
    only accurate when the estimate is also zero.
    """
    if real_rows <= 0:
        return reltuples <= 0
    if reltuples < 0:  # -1 means "never analyzed"
        return False
    return abs(reltuples - real_rows) / real_rows <= MESSAGE_STATS_RELTUPLES_REL_ERROR
