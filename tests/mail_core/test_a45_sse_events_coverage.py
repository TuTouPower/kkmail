"""A45: SSE_CORE_CLIENT_EVENTS must cover sync.request_updated and
CORE ∪ ARCHIVE must equal the full WIRE set (no silent drift)."""
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.realtime import events as events_mod


def test_sync_request_updated_in_core():
    assert OutboxEventType.SYNC_REQUEST_UPDATED.value in events_mod.SSE_CORE_CLIENT_EVENTS


def test_core_union_archive_equals_wire():
    union = set(events_mod.SSE_CORE_CLIENT_EVENTS) | set(events_mod.SSE_ARCHIVE_CLIENT_EVENTS)
    assert union == set(events_mod.SSE_WIRE_EVENTS)
    assert union == {e.value for e in OutboxEventType}
