"""Application-layer search (routes must not call search.index directly)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from mail_core.mail.application.queries import MessageListItem, messages_by_ids
from mail_core.search.index import count_messages as _count_messages
from mail_core.search.index import search_messages as _search_messages


@dataclass(frozen=True, slots=True)
class SearchPage:
    query: str
    items: list[MessageListItem]
    total: int
    offset: int
    next_offset: int | None


def search_message_ids(
    session: Session,
    *,
    query: str,
    account_ids: list[uuid.UUID] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[uuid.UUID]:
    return _search_messages(session, account_ids=account_ids, query=query, limit=limit, offset=offset)


def search_messages_page(
    session: Session,
    *,
    query: str,
    account_ids: list[uuid.UUID] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SearchPage:
    """Ranked search hydrated into list rows, with offset pagination + total."""
    ids = search_message_ids(session, query=query, account_ids=account_ids, limit=limit + 1, offset=offset)
    has_more = len(ids) > limit
    ids = ids[:limit]
    total = _count_messages(session, account_ids=account_ids, query=query)
    return SearchPage(
        query=query,
        items=messages_by_ids(session, ids),
        total=total,
        offset=offset,
        next_offset=offset + limit if has_more else None,
    )
