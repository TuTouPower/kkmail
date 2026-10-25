"""Cross-process mail provider outbound connection permits via PostgreSQL advisory locks (D10.5)."""

from __future__ import annotations

import contextlib
import logging
from typing import Iterator

from sqlalchemy import select, text
from sqlalchemy.orm import Session

log = logging.getLogger("mail_core.providers.connection_slots")

# Fixed 8 advisory lock keys in distinct namespace (0x4B4D_0000 + slot)
_SLOT_BASE_KEY = 0x4B4D_0000
TOTAL_SLOTS = 8
RESERVED_METADATA_SLOTS = 2  # slots 0 and 1 reserved for metadata/on-demand
BACKGROUND_START_SLOT = 2    # background archive uses slots 2..7


class ProviderCapacityUnavailable(RuntimeError):
    """Raised when global provider outbound connection limit (8) is saturated."""


@contextlib.contextmanager
def provider_connection_permit(session: Session, *, is_background: bool = False) -> Iterator[int]:
    """Acquire a temporary connection permit slot.

    Slots 0 and 1 are reserved for interactive on-demand / delta metadata.
    Background jobs may only claim from slots 2 to 7.
    """
    candidate_slots = range(BACKGROUND_START_SLOT, TOTAL_SLOTS) if is_background else range(0, TOTAL_SLOTS)
    acquired_slot: int | None = None

    for slot in candidate_slots:
        lock_id = _SLOT_BASE_KEY + slot
        got = session.scalar(select(text(f"pg_try_advisory_lock({lock_id})")))
        if got:
            acquired_slot = slot
            break

    if acquired_slot is None:
        raise ProviderCapacityUnavailable(
            f"all {'background' if is_background else 'global'} provider connection permits are in use"
        )

    try:
        yield acquired_slot
    finally:
        lock_id = _SLOT_BASE_KEY + acquired_slot
        try:
            session.execute(text(f"SELECT pg_advisory_unlock({lock_id})"))
        except Exception as exc:
            log.warning("failed to unlock provider permit slot %s: %s", acquired_slot, exc)
