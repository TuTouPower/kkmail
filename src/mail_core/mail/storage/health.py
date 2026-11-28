"""Storage health check helpers for database readiness."""

from __future__ import annotations

from sqlalchemy import text

import mail_core.db.session as session_mod


def get_current_schema_revision() -> str | None:
    """Fetch current alembic schema revision from database."""
    # t095 AC-005: AUTOCOMMIT keeps the readiness probe read-only at the
    # driver level (no implicit BEGIN/ROLLBACK on every healthcheck).
    with session_mod.get_engine().connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
