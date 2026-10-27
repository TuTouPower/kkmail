"""Application-layer search (routes must not call search.index directly)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from mail_core.mail.application.queries import MessageListItem, messages_by_ids
from mail_core.search.index import search_messages as _search_messages
from mail_core.search.index import search_messages_with_total as _search_messages_with_total


@dataclass(frozen=True, slots=True)
class SearchPage:
    query: str
    items: list[MessageListItem]
    total: int
    offset: int
    next_offset: int | None


MAX_SEARCH_OFFSET = 10_000
#: Same page-size ceiling the API route enforces (limit Query le=200) and
#: the search layer clamps to; enforced here so non-route callers cannot
#: bypass it (A115).
MAX_SEARCH_LIMIT = 200


def _validate_search_pagination(*, limit: int, offset: int) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= MAX_SEARCH_OFFSET:
        raise ValueError(f"offset must be between 0 and {MAX_SEARCH_OFFSET}")


def search_message_ids(
    session: Session,
    *,
    query: str,
    account_ids: list[uuid.UUID] | None = None,
    folder_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[uuid.UUID]:
    _validate_search_pagination(limit=limit, offset=offset)
    return _search_messages(session, account_ids=account_ids, query=query, folder_id=folder_id, limit=limit, offset=offset)


def search_messages_page(
    session: Session,
    *,
    query: str,
    account_ids: list[uuid.UUID] | None = None,
    folder_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> SearchPage:
    """Ranked search hydrated into list rows, with offset pagination + total."""
    _validate_search_pagination(limit=limit, offset=offset)
    ids, total = _search_messages_with_total(
        session,
        account_ids=account_ids,
        query=query,
        folder_id=folder_id,
        limit=limit + 1,
        offset=offset,
    )
    has_more = len(ids) > limit
    ids = ids[:limit]
    next_offset: int | None = None
    if has_more:
        cand = offset + limit
        if cand <= MAX_SEARCH_OFFSET:
            next_offset = cand
    return SearchPage(
        query=query,
        items=messages_by_ids(session, ids),
        total=total,
        offset=offset,
        next_offset=next_offset,
    )
