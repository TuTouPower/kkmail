"""Package C migration coverage (20261026_0025), PostgreSQL-backed.

Verifies design §12: existing worker jobs each gain their own
execution_generation; queued/running requests that cannot be reliably bound
are marked failed with ``execution_tracking_unavailable`` (IDs/history kept,
background jobs untouched); the binding table and scan_generation column
appear; ``current_job_id`` is dropped.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from mail_core.db.session import get_engine

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


def _get_alembic_config() -> Config:
    cfg = Config(str(ROOT / "src/mail_core/db/alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/mail_core/db/alembic"))
    safe_url = os.environ["MAIL_CORE_DATABASE_URL"].replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", safe_url)
    return cfg


def test_upgrade_0025_backfills_generations_and_fails_unbound_requests():
    cfg = _get_alembic_config()
    engine = get_engine()
    account_id = uuid.uuid4()
    job_id = uuid.uuid4()
    request_id = uuid.uuid4()
    target_id = uuid.uuid4()
    generation = uuid.uuid4()
    try:
        command.downgrade(cfg, "20261026_0024")
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO accounts (id, email, provider) VALUES (:id, :email, 'imap')"),
                {"id": account_id, "email": f"mig25-{account_id.hex[:8]}@example.com"},
            )
            conn.execute(
                text(
                    "INSERT INTO worker_jobs (id, job_type, account_id, status) "
                    "VALUES (:id, 'sync_folder_delta', :account_id, 'pending')"
                ),
                {"id": job_id, "account_id": account_id},
            )
            conn.execute(
                text(
                    "INSERT INTO sync_requests (id, client_request_id, mode, trigger, state, scope) "
                    "VALUES (:id, :crid, 'delta', 'manual', 'running', '{}'::jsonb)"
                ),
                {"id": request_id, "crid": f"mig25-{uuid.uuid4().hex}"},
            )
            conn.execute(
                text(
                    "INSERT INTO sync_request_targets "
                    "(id, request_id, account_id, current_job_id, target_key, requested_generation, state) "
                    "VALUES (:id, :rid, :aid, :jid, 'account:x:folder:all:role:all', :gen, 'running')"
                ),
                {"id": target_id, "rid": request_id, "aid": account_id, "jid": job_id, "gen": generation},
            )

        command.upgrade(cfg, "head")

        with engine.connect() as conn:
            job_generation = conn.scalar(
                text("SELECT execution_generation FROM worker_jobs WHERE id = :id"), {"id": job_id}
            )
            assert job_generation is not None
            req_state = conn.scalar(
                text("SELECT state FROM sync_requests WHERE id = :id"), {"id": request_id}
            )
            assert req_state == "failed"
            target_row = conn.execute(
                text("SELECT state, error_code FROM sync_request_targets WHERE id = :id"),
                {"id": target_id},
            ).one()
            assert target_row.state == "failed"
            assert target_row.error_code == "execution_tracking_unavailable"
            # The background job itself is untouched and still runnable.
            job_status = conn.scalar(
                text("SELECT status FROM worker_jobs WHERE id = :id"), {"id": job_id}
            )
            assert job_status == "pending"

        inspector = inspect(engine)
        target_columns = {c["name"] for c in inspector.get_columns("sync_request_targets")}
        assert "current_job_id" not in target_columns
        checkpoint_columns = {c["name"] for c in inspector.get_columns("sync_checkpoints")}
        assert "scan_generation" in checkpoint_columns
        assert "sync_request_target_jobs" in inspector.get_table_names()
    finally:
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM sync_requests WHERE id = :id"), {"id": request_id})
            conn.execute(text("DELETE FROM accounts WHERE id = :id"), {"id": account_id})
