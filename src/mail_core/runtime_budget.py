"""Single source of truth for the single-host runtime concurrency budget (t095).

Every consumer (DB pool, IDLE watcher, worker execution slots, and the LISTEN
direct connections) derives its allowance from this baseline so defaults cannot
drift across modules. Values target a single-process embedded self-hosted
deployment; the distributed profile may override upward explicitly.
"""

from __future__ import annotations

# Baseline single-process concurrency budget.
DEFAULT_TOTAL_SLOTS = 8
DEFAULT_BACKGROUND_START_SLOT = 2

# DB pool: small because one process uses it; overflow bounded. Distinct
# LISTEN connections (outbox + job wake) are reserved above this budget and
# are NOT counted in pool_size.
DEFAULT_DB_POOL_SIZE = 4
DEFAULT_DB_MAX_OVERFLOW = 4

# IDLE watcher: long-lived IMAP connections for the main inboxes; decoupled
# from the task-slot budget. 8 covers a realistic single-host inbox count.
DEFAULT_IDLE_QUOTA = 8

# Total client connections admitted to PostgreSQL (pool + overflow + the two
# LISTEN direct connections + headroom for maintenance). Exposed so operators
# can size max_connections consistently.
MAX_CLIENT_CONNECTIONS = 16
