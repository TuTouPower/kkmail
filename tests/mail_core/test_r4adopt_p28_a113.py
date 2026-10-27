"""A113: reclaim_stale_in_progress SELECT must use FOR UPDATE SKIP LOCKED."""
from __future__ import annotations
from datetime import timedelta
from unittest.mock import MagicMock
from sqlalchemy.dialects import postgresql
from mail_core.mail.application.remote_ops import reclaim_stale_in_progress

def _captured_sql():
    session = MagicMock()
    captured = {}
    def scalars(stmt, *a, **k):
        captured["stmt"] = stmt
        result = MagicMock()
        result.all.return_value = []
        return result
    session.scalars.side_effect = scalars
    n = reclaim_stale_in_progress(session, older_than=timedelta(minutes=15))
    assert n == 0
    stmt = captured["stmt"]
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))

def test_reclaim_select_uses_skip_locked():
    sql = _captured_sql().upper()
    assert "FOR UPDATE SKIP LOCKED" in sql
