"""Global mail-provider outbound connection budget (repair design §7 / R11).

The budget is 8 concurrent provider connections across *all* processes.
Slots are fixed (0-7): background archive traffic may only use slots 2-7
(max 6), so slots 0-1 always remain available to interactive / metadata
traffic.

Implementation model (replaces the former session-advisory-lock helper):

* Every active permit is held by ONE dedicated ``psycopg`` connection in
  autocommit mode that holds exactly one ``pg_try_advisory_lock`` slot key.
  The control connection is *never* returned to the business connection
  pool; releasing a permit unlocks and then closes it, so a dead worker
  releases its slots as soon as PostgreSQL notices the disconnect.
* A control connection never recursively acquires the re-entrant advisory
  lock: one control connection == at most one slot.
* :class:`TrafficClass` is propagated explicitly from the job type (and,
  for archive jobs, whether a ``message_id`` was specified) through
  ``build_provider`` into the provider / transport instances.  Provider
  hydration threads read the class from the provider instance — never
  from thread-local state.

When no database URL is configured there is no multi-process deployment
to coordinate (the backend refuses to run without one), so
:func:`default_permit_factory` falls back to a process-wide in-memory
factory that enforces the same 8/6 limits inside the process.  Tests use
that factory (or the dedicated one against a real PostgreSQL) to count
concurrent permits at the provider/transport boundary.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from enum import StrEnum
from typing import Any, Callable, Iterator, Protocol

log = logging.getLogger("mail_core.providers.connection_slots")

# Fixed 8 advisory lock keys in distinct namespace (0x4B4D_0000 + slot)
_SLOT_BASE_KEY = 0x4B4D_0000
TOTAL_SLOTS = 8
RESERVED_METADATA_SLOTS = 2  # slots 0 and 1 reserved for metadata/on-demand
BACKGROUND_START_SLOT = 2  # background archive uses slots 2..7

# Short reschedule delay for capacity/control deferrals.  Kept small: a
# slot frees as soon as any in-flight connection finishes.
CAPACITY_RETRY_SECONDS = 5.0


class TrafficClass(StrEnum):
    """Explicit provider-I/O traffic class carried by providers/transports."""

    FOREGROUND = "foreground"  # interactive / metadata / delta / push / on-demand
    BACKGROUND = "background"  # routine archive batch traffic only


def _coerce_traffic_class(value: Any) -> TrafficClass:
    if isinstance(value, TrafficClass):
        return value
    if isinstance(value, bool):
        return TrafficClass.BACKGROUND if value else TrafficClass.FOREGROUND
    text = str(value or "").strip().lower()
    if text in ("background", "bg", "archive"):
        return TrafficClass.BACKGROUND
    return TrafficClass.FOREGROUND


def candidate_slots(traffic_class: TrafficClass) -> range:
    if traffic_class is TrafficClass.BACKGROUND:
        return range(BACKGROUND_START_SLOT, TOTAL_SLOTS)
    return range(0, TOTAL_SLOTS)


def traffic_class_for_job(
    job_type: Any,
    *,
    message_id: Any = None,
    payload: dict | None = None,
) -> TrafficClass:
    """Derive the traffic class from the *actual* job type.

    Only routine archive batches are background traffic.  An archive job
    carrying a ``message_id`` is an on-demand body fetch initiated from
    the reader, so it is foreground and may use the reserved slots.
    Every other job type (folder discovery, metadata, delta, reconcile,
    remote push) is foreground.
    """
    mid = message_id
    if mid is None and payload:
        mid = payload.get("message_id")
    if str(job_type or "") == "archive_mime_batch" and not mid:
        return TrafficClass.BACKGROUND
    return TrafficClass.FOREGROUND


class ProviderCapacityUnavailable(RuntimeError):
    """Global provider connection budget (8 / 6 background) is saturated.

    This is a *deferral*, never a failure: callers must delay/reschedule
    the work without counting a business failure, an auth failure, or a
    remote-operation terminal state.
    """

    retry_after_seconds = CAPACITY_RETRY_SECONDS


class ProviderControlError(RuntimeError):
    """The dedicated slot control connection itself failed.

    The current execution must stop opening new provider connections,
    close the remote connections it already has, and leave its work
    resumable (same deferral semantics as capacity shortage).
    """

    retry_after_seconds = CAPACITY_RETRY_SECONDS


#: Errors that mean "delay and reschedule", never "fail".
CAPACITY_ERRORS: tuple[type[BaseException], ...] = (
    ProviderCapacityUnavailable,
    ProviderControlError,
)


def is_capacity_error(exc: BaseException | None) -> bool:
    return isinstance(exc, CAPACITY_ERRORS)


# ---------------------------------------------------------------------------
# Permit + backends
# ---------------------------------------------------------------------------


class _SlotBackend(Protocol):
    """One dedicated control connection holding at most one slot lock."""

    def try_lock(self, slot: int) -> bool: ...

    def release(self, slot: int) -> None:
        """Unlock ``slot`` and close the control connection."""
        ...


class ConnectionPermit:
    """One held connection slot.  ``release()`` is idempotent."""

    def __init__(self, *, slot: int, traffic_class: TrafficClass, backend: _SlotBackend) -> None:
        self.slot = slot
        self.traffic_class = traffic_class
        self._backend = backend
        self._released = False
        self._lock = threading.Lock()

    def release(self) -> None:
        with self._lock:
            if self._released:
                return
            self._released = True
        try:
            self._backend.release(self.slot)
        except Exception as exc:  # closing must never mask the caller's outcome
            log.warning("failed to release provider permit slot %s: %s", self.slot, exc)

    @property
    def released(self) -> bool:
        return self._released

    def __enter__(self) -> "ConnectionPermit":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.release()


class _PsycopgSlotBackend:
    """Dedicated psycopg autocommit control connection (one per permit)."""

    def __init__(self, dsn: str) -> None:
        import psycopg

        # A failure here is a control-plane failure, not a provider error.
        # A375: never interpolate the raw exception — psycopg connection
        # errors can embed the full DSN (host, user, password). Keep only
        # the redacted summary (exception class name + controlled fields)
        # via safe_error.
        from mail_core.security.redact import safe_error

        try:
            self._conn = psycopg.connect(dsn, autocommit=True)
        except Exception as exc:
            raise ProviderControlError(f"slot control connection failed: {safe_error(exc)}") from exc

    def try_lock(self, slot: int) -> bool:
        from mail_core.security.redact import safe_error

        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(%s)", (_SLOT_BASE_KEY + slot,))
                row = cur.fetchone()
            return bool(row and row[0])
        except Exception as exc:
            raise ProviderControlError(
                f"slot control lock failed for slot {slot}: {safe_error(exc)}"
            ) from exc

    def release(self, slot: int) -> None:
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_SLOT_BASE_KEY + slot,))
        except Exception:
            pass  # closing the session releases the lock anyway
        finally:
            try:
                self._conn.close()
            except Exception:
                pass


class _InMemorySlotState:
    """Process-wide slot registry shared by every in-memory factory."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.held: dict[int, TrafficClass] = {}
        self.current = 0
        self.peak = 0
        self.current_background = 0
        self.peak_background = 0

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "held_slots": sorted(self.held),
                "current": self.current,
                "peak": self.peak,
                "current_background": self.current_background,
                "peak_background": self.peak_background,
            }

    def reset(self) -> None:
        with self.lock:
            self.held.clear()
            self.current = 0
            self.peak = 0
            self.current_background = 0
            self.peak_background = 0


_IN_MEMORY_STATE = _InMemorySlotState()


class _InMemorySlotBackend:
    """Backend over the shared in-memory registry (single control handle)."""

    def __init__(self, state: _InMemorySlotState, traffic_class: TrafficClass) -> None:
        self._state = state
        self._traffic_class = traffic_class
        self._slot: int | None = None

    def try_lock(self, slot: int) -> bool:
        with self._state.lock:
            if slot in self._state.held:
                return False
            self._state.held[slot] = self._traffic_class
            self._slot = slot
            self._state.current += 1
            self._state.peak = max(self._state.peak, self._state.current)
            if self._traffic_class is TrafficClass.BACKGROUND:
                self._state.current_background += 1
                self._state.peak_background = max(
                    self._state.peak_background, self._state.current_background
                )
            return True

    def release(self, slot: int) -> None:
        with self._state.lock:
            if self._state.held.pop(slot, None) is not None:
                self._state.current -= 1
                if self._traffic_class is TrafficClass.BACKGROUND:
                    self._state.current_background -= 1
            self._slot = None


class PermitFactory(Protocol):
    """Acquires connection permits for one traffic class at a time."""

    def acquire(self, traffic_class: TrafficClass | str | bool) -> ConnectionPermit: ...


def _acquire_with_backend(
    make_backend: Callable[[TrafficClass], _SlotBackend],
    traffic_class: TrafficClass,
) -> ConnectionPermit:
    """Open ONE control connection and claim the first free candidate slot."""
    backend = make_backend(traffic_class)  # may raise ProviderControlError
    try:
        for slot in candidate_slots(traffic_class):
            if backend.try_lock(slot):
                return ConnectionPermit(slot=slot, traffic_class=traffic_class, backend=backend)
    except BaseException:
        # Lock attempt failed mid-scan: close the control connection so it
        # cannot leak a slot it may have half-claimed, then propagate.
        try:
            backend.release(-1)
        except Exception:
            pass
        raise
    # Saturated: close the control connection before reporting capacity.
    try:
        backend.release(-1)
    except Exception:
        pass
    scope = "background" if traffic_class is TrafficClass.BACKGROUND else "global"
    raise ProviderCapacityUnavailable(
        f"all {scope} provider connection permits are in use"
    )


class DedicatedSlotPermitFactory:
    """Production factory: one dedicated psycopg control connection per permit."""

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn

    def _resolve_dsn(self) -> str:
        if self._dsn:
            return self._dsn
        raw = (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip()
        if not raw:
            raise ProviderControlError("MAIL_CORE_DATABASE_URL is required for slot control")
        # psycopg takes a plain postgresql:// DSN; strip the SQLAlchemy
        # driver suffix when present.
        from sqlalchemy.engine.url import make_url

        url = make_url(raw)
        if url.drivername.startswith("postgresql"):
            url = url.set(drivername="postgresql")
        return url.render_as_string(hide_password=False)

    def acquire(self, traffic_class: TrafficClass | str | bool) -> ConnectionPermit:
        tc = _coerce_traffic_class(traffic_class)
        dsn = self._resolve_dsn()
        return _acquire_with_backend(lambda _tc: _PsycopgSlotBackend(dsn), tc)


class InMemoryPermitFactory:
    """Process-local factory enforcing the same 8/6 limits (tests / no-DB)."""

    def __init__(self, state: _InMemorySlotState | None = None) -> None:
        self._state = state or _IN_MEMORY_STATE

    def acquire(self, traffic_class: TrafficClass | str | bool) -> ConnectionPermit:
        tc = _coerce_traffic_class(traffic_class)
        return _acquire_with_backend(
            lambda klass: _InMemorySlotBackend(self._state, klass), tc
        )

    def snapshot(self) -> dict[str, Any]:
        return self._state.snapshot()

    def reset(self) -> None:
        self._state.reset()


def default_permit_factory() -> PermitFactory:
    """Dedicated-connection factory when a DB URL exists, else in-memory."""
    if (os.environ.get("MAIL_CORE_DATABASE_URL") or "").strip():
        return DedicatedSlotPermitFactory()
    return InMemoryPermitFactory()


def acquire_permit(
    permit_factory: PermitFactory | None,
    traffic_class: TrafficClass | str | bool,
) -> ConnectionPermit | None:
    """Acquire via ``permit_factory``; ``None`` factory means unwired (tests)."""
    if permit_factory is None:
        return None
    return permit_factory.acquire(_coerce_traffic_class(traffic_class))


@contextlib.contextmanager
def permit_scope(
    permit_factory: PermitFactory | None,
    traffic_class: TrafficClass | str | bool,
) -> Iterator[ConnectionPermit | None]:
    """Context manager form of :func:`acquire_permit` (no-op without a factory)."""
    permit = acquire_permit(permit_factory, traffic_class)
    if permit is None:
        yield None
        return
    try:
        yield permit
    finally:
        permit.release()


# ---------------------------------------------------------------------------
# Backwards-compatible helper (legacy session-based call sites / PG tests)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def provider_connection_permit(
    session: Any = None,
    *,
    traffic_class: TrafficClass | str | bool | None = None,
    is_background: bool | None = None,
    permit_factory: PermitFactory | None = None,
) -> Iterator[int]:
    """Acquire a connection permit and yield the slot number.

    Legacy callers passed a business ``Session`` positionally.  The
    session is *not* used for locking any more (design §7 forbids holding
    a session advisory lock on a pooled connection); a dedicated control
    connection is opened instead and closed on release.
    """
    if traffic_class is None:
        traffic_class = TrafficClass.BACKGROUND if is_background else TrafficClass.FOREGROUND
    factory = permit_factory or default_permit_factory()
    permit = factory.acquire(_coerce_traffic_class(traffic_class))
    try:
        yield permit.slot
    finally:
        permit.release()
