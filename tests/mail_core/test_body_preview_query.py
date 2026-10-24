from __future__ import annotations

import uuid
from types import SimpleNamespace

from mail_core.mail.application.queries import _BODY_PREVIEW_SOURCE_CHARS, _body_previews


def test_body_preview_query_limits_body_columns_in_sql():
    class Result:
        def all(self):
            return []

    class Session:
        statement = None

        def execute(self, statement):
            self.statement = statement
            return Result()

    session = Session()
    _body_previews(session, [SimpleNamespace(id=uuid.uuid4(), snippet=None)])

    compiled = session.statement.compile()
    sql = str(compiled).lower()
    assert sql.count("substr(") == 2
    assert "text_plain" in sql
    assert "text_html" in sql
    assert list(compiled.params.values()).count(_BODY_PREVIEW_SOURCE_CHARS) == 2
