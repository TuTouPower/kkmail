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
DEFAULT_LISTEN_CONNECTIONS = 2  # 1 outbox LISTEN + 1 worker job-wake LISTEN
DEFAULT_MAINTENANCE_HEADROOM = 6  # startup migrations, health/ops, ad-hoc CLI

# IDLE watcher: long-lived IMAP connections for the main inboxes; decoupled
# from the task-slot budget. 8 covers a realistic single-host inbox count.
DEFAULT_IDLE_QUOTA = 8

# Data-plane client connection ceiling admitted to PostgreSQL:
#   data-plane pool (4 + 4 = 8) + LISTEN (2) + maintenance/migration headroom (6) = 16.
MAX_CLIENT_CONNECTIONS = (
    DEFAULT_DB_POOL_SIZE
    + DEFAULT_DB_MAX_OVERFLOW
    + DEFAULT_LISTEN_CONNECTIONS
    + DEFAULT_MAINTENANCE_HEADROOM
)

# Control-plane provider slot permits (`DedicatedSlotPermitFactory`) hold one
# dedicated autocommit psycopg connection per active `pg_try_advisory_lock`
# slot (`DEFAULT_TOTAL_SLOTS = 8`). Worst-case single-host peak: 16 + 8 = 24,
# comfortably bounded inside Compose PostgreSQL `max_connections = 40`.
MAX_TOTAL_PG_CONNECTIONS = MAX_CLIENT_CONNECTIONS + DEFAULT_TOTAL_SLOTS
COMPOSE_PG_MAX_CONNECTIONS = 40
