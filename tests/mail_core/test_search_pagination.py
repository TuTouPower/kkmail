from __future__ import annotations

import uuid

from mail_core.search.index import search_messages_with_total


def test_search_page_reads_total_with_the_ranked_id_query():
    ids = [uuid.uuid4(), uuid.uuid4()]

    class Result:
        def all(self):
            return [(ids[0], 23), (ids[1], 23)]

    class Session:
        statements = []

        def execute(self, statement, params):
            self.statements.append(str(statement))
            return Result()

    session = Session()
    page_ids, total = search_messages_with_total(
        session,
        account_ids=None,
        query="invoice",
        limit=10,
        offset=10,
    )

    assert page_ids == ids
    assert total == 23
    assert len(session.statements) == 1
    assert "count(*) over ()" in session.statements[0].lower()


def test_search_page_counts_when_offset_returns_no_window_rows():
    class Result:
        def __init__(self, rows):
            self.rows = rows

        def all(self):
            return self.rows

        def scalar(self):
            return 23

    class Session:
        def __init__(self):
            self.statements = []

        def execute(self, statement, params):
            self.statements.append(str(statement))
            return Result([] if len(self.statements) == 1 else None)

    session = Session()
    page_ids, total = search_messages_with_total(
        session,
        account_ids=None,
        query="invoice",
        limit=10,
        offset=30,
    )

    assert page_ids == []
    assert total == 23
    assert len(session.statements) == 2
