"""CLI routing for the one-shot Gmail label backfill (t088)."""

from __future__ import annotations

import argparse
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest

import mail_core.db.session as db_session
import mail_core.sync.label_backfill as label_backfill
from mail_core.__main__ import _run_label_backfill
from mail_core.sync.label_backfill import BackfillResult

TARGET = uuid.uuid4()


class _Session:
    def __init__(self, found: bool):
        self.found = found

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, _model, key):
        if self.found and key == TARGET:
            return SimpleNamespace(id=TARGET, email="cli@gmail.com", config={}, label_backfill_completed_at=None)
        return None


def _parser():
    return argparse.ArgumentParser(prog="test")


def test_valid_account_id_routes_to_backfill(monkeypatch):
    monkeypatch.setattr(db_session, "get_session_factory", lambda: lambda: _Session(True))
    calls = []

    def fake(Session, account_id, *, force=False):
        calls.append((account_id, force))
        return BackfillResult(account_id, "completed", 1, 1)

    monkeypatch.setattr(label_backfill, "backfill_account", fake)
    assert _run_label_backfill(
        SimpleNamespace(account_id=str(TARGET), force=True), _parser()
    ) == 0
    assert calls == [(TARGET, True)]


def test_missing_account_returns_failure(monkeypatch):
    monkeypatch.setattr(db_session, "get_session_factory", lambda: lambda: _Session(False))
    assert _run_label_backfill(
        SimpleNamespace(account_id=str(TARGET), force=False), _parser()
    ) == 1


def test_failed_backfill_returns_failure(monkeypatch):
    monkeypatch.setattr(db_session, "get_session_factory", lambda: lambda: _Session(True))
    monkeypatch.setattr(
        label_backfill,
        "backfill_account",
        lambda Session, account_id, *, force=False: BackfillResult(account_id, "failed"),
    )
    assert _run_label_backfill(
        SimpleNamespace(account_id=str(TARGET), force=False), _parser()
    ) == 1


def test_invalid_account_id_reports_argument_error(monkeypatch):
    monkeypatch.setattr(db_session, "get_session_factory", lambda: lambda: _Session(True))
    with pytest.raises(SystemExit):
        _run_label_backfill(SimpleNamespace(account_id="not-a-uuid", force=False), _parser())


def test_maintenance_lease_ttl_covers_slow_gmail_pages():
    assert label_backfill.LEASE_TTL >= timedelta(minutes=5)
