"""A84: root job is delta -> _inflight must still check metadata jobs.

Runs against the real PostgreSQL schema created by ``alembic upgrade head``.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

from mail_core.db.session import get_session_factory
from mail_core.mail.application.sync_requests import _inflight_full_root_generation
from mail_core.mail.storage.models import WorkerJob

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)


def _job(account_id, dedupe, payload, status="pending"):
    return WorkerJob(id=uuid.uuid4(), execution_generation=uuid.uuid4(), job_type="sync_folder_delta" if "metadata" not in dedupe else "sync_folder_metadata", dedupe_key=dedupe, payload=payload, status=status, run_after=_NOW, created_at=_NOW, updated_at=_NOW)


def test_delta_root_still_finds_metadata_full_generation():
    Session = get_session_factory()
    account_id = uuid.uuid4()
    folder_id = uuid.uuid4()
    gen = uuid.uuid4()
    with Session() as session:
        session.add(_job(account_id, f"sync:{account_id}", {"request_id": "x"}))
        session.add(_job(account_id, f"metadata:{account_id}:{folder_id}", {"folder_id": str(folder_id), "full": True, "scan_generation": str(gen)}))
        session.commit()
        assert _inflight_full_root_generation(session, account_id) == gen


def test_delta_root_without_metadata_full_returns_none():
    Session = get_session_factory()
    account_id = uuid.uuid4()
    with Session() as session:
        session.add(_job(account_id, f"sync:{account_id}", {"request_id": "x"}))
        session.commit()
        assert _inflight_full_root_generation(session, account_id) is None


def test_full_root_still_returned_directly():
    Session = get_session_factory()
    account_id = uuid.uuid4()
    gen = uuid.uuid4()
    with Session() as session:
        session.add(_job(account_id, f"sync:{account_id}", {"full": True, "scan_generation": str(gen)}))
        session.commit()
        assert _inflight_full_root_generation(session, account_id) == gen
