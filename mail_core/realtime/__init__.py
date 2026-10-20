from mail_core.realtime.dispatcher import OutboxDispatcher, get_dispatcher
from mail_core.realtime.outbox import OutboxItem, fetch_since, fetch_undispatched, mark_dispatched

__all__ = [
    "OutboxDispatcher",
    "OutboxItem",
    "fetch_since",
    "fetch_undispatched",
    "get_dispatcher",
    "mark_dispatched",
]
