"""SQLite DDL derived from ORM models for hand-written schema fixtures.

Sync/outbox unit tests drive production code against in-memory SQLite with
hand-written DDL. Deriving a table from its ORM definition keeps the fixture
from drifting when migrations add columns (for example
``accounts.recipient_addresses`` in migration 0027). PostgreSQL-specific
``JSONB`` defaults are rendered as plain ``JSON`` because SQLite cannot parse
the ``::jsonb`` cast.
"""

from __future__ import annotations

from sqlalchemy.dialects import sqlite
from sqlalchemy.schema import CreateTable, Table


def sqlite_table_ddl(table: Table) -> str:
    """Compile ``table`` as SQLite CREATE TABLE, mapping JSONB to JSON."""
    compiled = str(CreateTable(table).compile(dialect=sqlite.dialect()))
    return compiled.replace("JSONB", "JSON").replace("::jsonb", "")
