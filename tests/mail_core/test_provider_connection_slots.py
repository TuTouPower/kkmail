"""Tests for provider outbound connection permits."""

from __future__ import annotations

import os
import pytest

from mail_core.providers.connection_slots import (
    InMemoryPermitFactory,
    ProviderCapacityUnavailable,
    TrafficClass,
    get_total_slots,
    provider_connection_permit,
)


@pytest.fixture(autouse=True)
def _clean_in_memory_slots():
    """Ensure in-memory slot state is reset between tests in unit mode."""
    if not os.environ.get("MAIL_CORE_DATABASE_URL"):
        InMemoryPermitFactory().reset()
        yield
        InMemoryPermitFactory().reset()
    else:
        yield


def test_provider_connection_permit_lifecycle():
    with provider_connection_permit(traffic_class=TrafficClass.FOREGROUND) as slot1:
        assert 0 <= slot1 < get_total_slots()

        # Background permit should take a background slot (>=2)
        with provider_connection_permit(traffic_class=TrafficClass.BACKGROUND) as slot2:
            assert 2 <= slot2 < get_total_slots()
            assert slot2 != slot1


def test_background_permits_cannot_steal_reserved_metadata_slots():
    contexts = []
    try:
        # Exhaust all 6 background slots (2..7)
        for _ in range(6):
            ctx = provider_connection_permit(traffic_class=TrafficClass.BACKGROUND)
            slot = ctx.__enter__()
            assert 2 <= slot < get_total_slots()
            contexts.append((ctx, slot))

        # 7th background permit must fail because slots 0 and 1 are reserved!
        with pytest.raises(ProviderCapacityUnavailable, match="background"):
            with provider_connection_permit(traffic_class=TrafficClass.BACKGROUND):
                pass

        # But a foreground/metadata permit can STILL succeed in slot 0 or 1!
        with provider_connection_permit(traffic_class=TrafficClass.FOREGROUND) as fg_slot:
            assert fg_slot in (0, 1)

    finally:
        for ctx, _ in contexts:
            try:
                ctx.__exit__(None, None, None)
            except Exception:
                pass
