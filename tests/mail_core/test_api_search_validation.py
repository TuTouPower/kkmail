import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException

import mail_core.api.mail as mail_api


@pytest.mark.parametrize("query", [" ", "\t\n", "   \t  "])
def test_search_rejects_whitespace_only_query_before_database_access(query):
    with pytest.raises(HTTPException) as exc_info:
        mail_api.api_search(q=query)

    assert exc_info.value.status_code == 422


def test_search_strips_query_before_search(monkeypatch):
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    search = Mock(return_value=SimpleNamespace(query="cats", items=[], total=0, offset=0, next_offset=None))
    monkeypatch.setattr(mail_api, "get_session_factory", lambda: Session)
    monkeypatch.setattr(mail_api, "search_messages_page", search)
    monkeypatch.setattr(mail_api, "account_emails_by_id", Mock(return_value={}))
    enabled_ids = [uuid.UUID(int=1)]
    monkeypatch.setattr(mail_api, "enabled_account_ids", lambda _session: enabled_ids)

    result = mail_api.api_search(q="  cats  ", limit=50, offset=0)

    assert result.query == "cats"
    assert search.call_args.kwargs["query"] == "cats"
    assert search.call_args.kwargs["account_ids"] == enabled_ids
