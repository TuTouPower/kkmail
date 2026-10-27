"""A247: mutating *_app functions share one _run_in_session transaction boundary."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import mail_core.mail.application.accounts as accounts_app


class _FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _patch_factory(monkeypatch, session):
    monkeypatch.setattr(accounts_app, "get_session_factory", lambda: lambda: session)


def test_run_in_session_commits_once_on_success_and_rollbacks_on_error():
    assert hasattr(accounts_app, "_run_in_session")

    ok_session = _FakeSession()
    _patch_factory_for_context = accounts_app.get_session_factory
    try:
        accounts_app.get_session_factory = lambda: lambda: ok_session  # type: ignore[assignment]
        with accounts_app._run_in_session() as session:
            assert session is ok_session
        assert ok_session.commits == 1
        assert ok_session.rollbacks == 0

        bad_session = _FakeSession()
        accounts_app.get_session_factory = lambda: lambda: bad_session  # type: ignore[assignment]
        with pytest.raises(RuntimeError, match="boom"):
            with accounts_app._run_in_session():
                raise RuntimeError("boom")
        assert bad_session.commits == 0
        assert bad_session.rollbacks == 1
    finally:
        accounts_app.get_session_factory = _patch_factory_for_context  # type: ignore[assignment]


def test_mutating_apps_commit_once_on_success(monkeypatch):
    session = _FakeSession()
    _patch_factory(monkeypatch, session)
    monkeypatch.setattr(accounts_app, "delete_account", lambda s, aid: None)
    accounts_app.delete_account_app(uuid.uuid4())
    assert session.commits == 1
    assert session.rollbacks == 0

    session2 = _FakeSession()
    _patch_factory(monkeypatch, session2)
    job_id = uuid.uuid4()
    monkeypatch.setattr(accounts_app, "enqueue_account_sync", lambda s, aid: job_id)
    result = accounts_app.sync_account_app(uuid.uuid4())
    assert result.job_id == str(job_id)
    assert session2.commits == 1

    session3 = _FakeSession()
    _patch_factory(monkeypatch, session3)
    group = SimpleNamespace(id=uuid.uuid4(), name="Work", color=None, sort_order=0)
    monkeypatch.setattr(accounts_app, "create_group", lambda s, name, color=None: group)
    dto = accounts_app.create_group_app(name="Work")
    assert dto.name == "Work"
    assert session3.commits == 1


def test_mutating_app_failure_rollbacks_and_reraises(monkeypatch):
    session = _FakeSession()
    _patch_factory(monkeypatch, session)

    def failing_delete(s, aid):
        raise LookupError("account not found")

    monkeypatch.setattr(accounts_app, "delete_account", failing_delete)
    with pytest.raises(LookupError, match="account not found"):
        accounts_app.delete_account_app(uuid.uuid4())
    assert session.commits == 0
    assert session.rollbacks == 1


def test_read_only_app_does_not_commit(monkeypatch):
    session = _FakeSession()
    _patch_factory(monkeypatch, session)
    monkeypatch.setattr(accounts_app, "list_groups", lambda s: [])
    assert accounts_app.list_groups_app() == []
    assert session.commits == 0
    assert session.rollbacks == 0
