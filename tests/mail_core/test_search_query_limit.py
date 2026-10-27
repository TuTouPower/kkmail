"""A353: the search layer itself must bound query length (route used 256)."""

from __future__ import annotations

from mail_core.search.index import count_messages, search_messages, search_messages_with_total


class _Result:
    def all(self):
        return []

    def scalar(self):
        return 0


class _Session:
    def __init__(self):
        self.parameters = []

    def execute(self, _statement, parameters):
        self.parameters.append(dict(parameters))
        return _Result()


def test_search_layer_truncates_overlong_query_to_route_limit():
    session = _Session()
    long_query = "x" * 300

    assert search_messages(session, account_ids=None, query=long_query) == []
    assert count_messages(session, account_ids=None, query=long_query) == 0
    assert search_messages_with_total(session, account_ids=None, query=long_query) == ([], 0)

    assert len(session.parameters) == 3
    for params in session.parameters:
        assert params["q"] == "x" * 256
        assert params["like_q"] == "x" * 256


def test_search_layer_keeps_short_query_untouched():
    session = _Session()
    search_messages(session, account_ids=None, query="hello")
    assert session.parameters[0]["q"] == "hello"
    assert session.parameters[0]["like_q"] == "hello"
