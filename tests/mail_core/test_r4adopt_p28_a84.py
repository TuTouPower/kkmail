"""A84: root job is delta -> _inflight must still check metadata jobs."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from mail_core.mail.application.sync_requests import _inflight_full_root_generation
from mail_core.mail.storage.models import WorkerJob

_DDL = """
CREATE TABLE worker_jobs (
    id CHAR(36) PRIMARY KEY,
    execution_generation CHAR(36) NOT NULL,
    job_type VARCHAR(64) NOT NULL,
    account_id CHAR(36),
    dedupe_key VARCHAR(128),
    payload JSON NOT NULL DEFAULT '{}',
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    priority INTEGER NOT NULL DEFAULT 100,
    run_after DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    failure_attempts INTEGER NOT NULL DEFAULT 0,
    locked_by VARCHAR(128),
    locked_at DATETIME,
    last_error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
)
"""
_NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)

def _session():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text(_DDL))
    return sessionmaker(bind=engine)()

def _job(account_id, dedupe, payload, status="pending"):
    return WorkerJob(id=uuid.uuid4(), execution_generation=uuid.uuid4(), job_type="sync_folder_delta" if "metadata" not in dedupe else "sync_folder_metadata", account_id=account_id, dedupe_key=dedupe, payload=payload, status=status, run_after=_NOW, created_at=_NOW, updated_at=_NOW)

def test_delta_root_still_finds_metadata_full_generation():
    session = _session()
    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    gen = uuid.uuid4()
    # root sync job is a delta (no full flag)
    session.add(_job(account_id, f"sync:{account_id}", {"request_id": "x"}))
    session.add(_job(account_id, f"metadata:{account_id}:{folder_id}", {"folder_id": str(folder_id), "full": True, "scan_generation": str(gen)}))
    session.commit()
    assert _inflight_full_root_generation(session, account_id) == gen

def test_delta_root_without_metadata_full_returns_none():
    session = _session()
    account_id = uuid.uuid4()
    session.add(_job(account_id, f"sync:{account_id}", {"request_id": "x"}))
    session.commit()
    assert _inflight_full_root_generation(session, account_id) is None

def test_full_root_still_returned_directly():
    session = _session()
    account_id = uuid.uuid4()
    gen = uuid.uuid4()
    session.add(_job(account_id, f"sync:{account_id}", {"full": True, "scan_generation": str(gen)}))
    session.commit()
    assert _inflight_full_root_generation(session, account_id) == gen
