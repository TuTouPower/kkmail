from mail_core.search.index import count_messages, search_messages, search_messages_with_total


class _Result:
    def all(self):
        return []

    def scalar(self):
        return 0


class _Session:
    def __init__(self):
        self.statements = []
        self.parameters = []

    def execute(self, statement, parameters):
        self.statements.append(str(statement))
        self.parameters.append(dict(parameters))
        return _Result()


def test_search_escapes_like_metacharacters_only_for_ilike_branches():
    session = _Session()
    query = "%_\\x"

    assert search_messages(session, account_ids=None, query=query) == []
    assert count_messages(session, account_ids=None, query=query) == 0
    assert search_messages_with_total(session, account_ids=None, query=query) == ([], 0)

    assert len(session.statements) == 3
    for statement, parameters in zip(session.statements, session.parameters):
        assert parameters["q"] == query
        assert parameters["like_q"] == r"\%\_\\x"
        assert statement.count("ESCAPE E'\\\\'") == 2
