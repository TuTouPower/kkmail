"""Transient queue retention contract (t094 AC-003 / AC-007).

Both queues are transport buffers, not audit archives. Their windows are short,
fixed, and expressed in code (no product-level env switch). SSE replay and
sync-request settlement have their own authoritative watermarks, so a client
that falls behind the window must resync rather than expect history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import threading
import time

from sqlalchemy import event, text
from sqlalchemy.orm import Session, SessionTransaction

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
MESSAGE_STATS_ANALYZE_COOLDOWN_SECONDS = 300.0
MESSAGE_STATS_MIN_INTERVAL_S = MESSAGE_STATS_ANALYZE_COOLDOWN_SECONDS

_TX_INFO_KEY = "_message_stats_txs"
_message_stats_lock = threading.Lock()
_last_message_stats_analyze_at: float = float("-inf")
_pending_message_stats_rows: int = 0
_state_epoch: int = 0
_hooks_lock = threading.Lock()
_hooks_installed = False


@dataclass
class _TxMessageStatsState:
    tx: SessionTransaction
    epoch: int
    unaccounted_rows: int = 0
    analyzed: bool = False
    analyzed_pending_snapshot: int = 0


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


def _on_after_commit(session: Session) -> None:
    global _last_message_stats_analyze_at, _pending_message_stats_rows
    txs = session.info.get(_TX_INFO_KEY)
    if not txs:
        return
    if session.in_nested_transaction():
        tx = session.get_nested_transaction()
        if tx is None:
            return
        state = txs.pop(id(tx), None)
        if state is None:
            return
        parent = tx.parent
        if parent is not None:
            parent_state = txs.get(id(parent))
            if parent_state is None:
                parent_state = _TxMessageStatsState(tx=parent, epoch=state.epoch)
                txs[id(parent)] = parent_state
            if state.analyzed:
                parent_state.analyzed = True
                parent_state.analyzed_pending_snapshot = max(
                    parent_state.analyzed_pending_snapshot,
                    state.analyzed_pending_snapshot,
                )
                parent_state.unaccounted_rows = state.unaccounted_rows
            else:
                parent_state.unaccounted_rows += state.unaccounted_rows
        return

    tx = session.get_transaction()
    if tx is None:
        return
    state = txs.pop(id(tx), None)
    if not txs:
        session.info.pop(_TX_INFO_KEY, None)
    if state is None:
        return
    with _message_stats_lock:
        if state.epoch != _state_epoch:
            return
        if state.analyzed:
            _last_message_stats_analyze_at = time.monotonic()
            _pending_message_stats_rows = max(
                0,
                _pending_message_stats_rows - state.analyzed_pending_snapshot,
            ) + state.unaccounted_rows
        else:
            _pending_message_stats_rows += state.unaccounted_rows


def _on_after_transaction_end(session: Session, transaction: SessionTransaction) -> None:
    txs = session.info.get(_TX_INFO_KEY)
    if not txs:
        return
    txs.pop(id(transaction), None)
    if not txs:
        session.info.pop(_TX_INFO_KEY, None)


def _ensure_session_hooks_installed() -> None:
    global _hooks_installed
    if _hooks_installed:
        return
    with _hooks_lock:
        if _hooks_installed:
            return
        event.listen(Session, "after_commit", _on_after_commit)
        event.listen(Session, "after_transaction_end", _on_after_transaction_end)
        _hooks_installed = True


def _is_postgresql_session(session: Session) -> bool:
    try:
        bind = session.get_bind()
    except Exception:
        return False
    dialect = getattr(bind, "dialect", None)
    return getattr(dialect, "name", None) == "postgresql"


def _run_message_tables_analyze(session: Session) -> bool:
    """Run ANALYZE on all declared message tables within the active PG transaction."""
    if not _is_postgresql_session(session):
        return False
    for table in MESSAGE_STATS_TABLES:
        session.execute(text(f"ANALYZE {table}"))
    return True


def _tx_chain(tx: SessionTransaction) -> list[SessionTransaction]:
    chain: list[SessionTransaction] = []
    cur: SessionTransaction | None = tx
    while cur is not None:
        chain.append(cur)
        if not cur.nested:
            break
        cur = cur.parent
    return chain


def _maybe_analyze_in_tx(session: Session, *, added_rows: int = 0) -> bool:
    if not isinstance(session, Session):
        return False
    _ensure_session_hooks_installed()

    if added_rows > 0:
        if not session.in_transaction():
            session.begin()
        tx = session.get_nested_transaction() or session.get_transaction()
        if tx is None:
            return False
        txs = session.info.setdefault(_TX_INFO_KEY, {})
        state = txs.get(id(tx))
        if state is None:
            with _message_stats_lock:
                epoch = _state_epoch
            state = _TxMessageStatsState(tx=tx, epoch=epoch)
            txs[id(tx)] = state
        state.unaccounted_rows += added_rows
    else:
        tx = (
            (session.get_nested_transaction() or session.get_transaction())
            if session.in_transaction()
            else None
        )
        txs = session.info.get(_TX_INFO_KEY) or {}

    chain = _tx_chain(tx) if tx is not None else []
    already_analyzed = any(
        (entry := txs.get(id(t))) is not None and entry.analyzed
        for t in chain
    )
    chain_unaccounted = sum(
        txs[id(t)].unaccounted_rows
        for t in chain
        if id(t) in txs
    )

    with _message_stats_lock:
        pending_snapshot = _pending_message_stats_rows
        cooldown_ready = (
            (time.monotonic() - _last_message_stats_analyze_at)
            >= MESSAGE_STATS_ANALYZE_COOLDOWN_SECONDS
        )
        epoch = _state_epoch

    if (
        already_analyzed
        or not cooldown_ready
        or not is_bulk_message_sync(pending_snapshot + chain_unaccounted)
    ):
        return False

    if not session.in_transaction():
        session.begin()
    tx = session.get_nested_transaction() or session.get_transaction()
    if tx is None:
        return False

    if not _run_message_tables_analyze(session):
        return False

    txs = session.info.setdefault(_TX_INFO_KEY, {})
    state = txs.get(id(tx))
    if state is None:
        state = _TxMessageStatsState(tx=tx, epoch=epoch)
        txs[id(tx)] = state
    state.analyzed = True
    state.analyzed_pending_snapshot = pending_snapshot
    state.unaccounted_rows = 0
    return True


def record_message_stats_rows(session: Session, changed_rows: int) -> bool:
    """Track message-table row changes in ``session`` and ANALYZE post-threshold.

    Accumulates changed row counts across transactions (and inside the 300s
    cooldown window) and updates cooldown/pending counters only in SQLAlchemy's
    ``after_commit`` once the root transaction commits. Returns True when this
    call executed ``ANALYZE`` inside the active transaction.
    """
    changed = int(changed_rows)
    if changed <= 0:
        return False
    return _maybe_analyze_in_tx(session, added_rows=changed)


def flush_deferred_message_stats(session: Session) -> bool:
    """Run deferred message-table ANALYZE if pending rows >= threshold and cooldown expired."""
    return _maybe_analyze_in_tx(session, added_rows=0)


def refresh_message_stats_if_bulk(session: Session, changed_rows: int) -> bool:
    """Shared bulk-writer entry point delegating to :func:`record_message_stats_rows`."""
    return record_message_stats_rows(session, changed_rows)


def last_message_stats_analyze_at() -> float:
    """Return monotonic timestamp of the last committed message-table ANALYZE."""
    with _message_stats_lock:
        return _last_message_stats_analyze_at


def pending_message_stats_rows() -> int:
    """Return committed changed message rows waiting for message-table ANALYZE."""
    with _message_stats_lock:
        return _pending_message_stats_rows


def reset_message_stats_state() -> None:
    """Reset process-local message stats tracking state (tests only)."""
    global _last_message_stats_analyze_at, _pending_message_stats_rows, _state_epoch
    with _message_stats_lock:
        _last_message_stats_analyze_at = float("-inf")
        _pending_message_stats_rows = 0
        _state_epoch += 1
