"""Tests for cross-process provider outbound connection permits (D10.5)."""

import os
import pytest

from mail_core.db.session import get_session_factory
from mail_core.providers.connection_slots import (
    ProviderCapacityUnavailable,
    TOTAL_SLOTS,
    provider_connection_permit,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def test_provider_connection_permit_lifecycle():
    Session = get_session_factory()
    with Session() as s1:
        with provider_connection_permit(s1, is_background=False) as slot1:
            assert 0 <= slot1 < TOTAL_SLOTS

            # Background permit should take a background slot (>=2)
            with Session() as s2:
                with provider_connection_permit(s2, is_background=True) as slot2:
                    assert 2 <= slot2 < TOTAL_SLOTS
                    assert slot2 != slot1


def test_background_permits_cannot_steal_reserved_metadata_slots():
    Session = get_session_factory()
    sessions = [Session() for _ in range(6)]
    contexts = []
    try:
        # Exhaust all 6 background slots (2..7)
        for i in range(6):
            ctx = provider_connection_permit(sessions[i], is_background=True)
            slot = ctx.__enter__()
            assert 2 <= slot < TOTAL_SLOTS
            contexts.append((ctx, slot))

        # 7th background permit must fail because slots 0 and 1 are reserved!
        with Session() as s_overflow:
            with pytest.raises(ProviderCapacityUnavailable, match="background"):
                with provider_connection_permit(s_overflow, is_background=True):
                    pass

        # But a foreground/metadata permit can STILL succeed in slot 0 or 1!
        with Session() as s_foreground:
            with provider_connection_permit(s_foreground, is_background=False) as fg_slot:
                assert fg_slot in (0, 1)

    finally:
        for ctx, _ in contexts:
            try:
                ctx.__exit__(None, None, None)
            except Exception:
                pass
        for s in sessions:
            s.close()
