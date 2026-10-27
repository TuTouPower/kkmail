"""A180: mark-all-read loop must be bounded and fail loudly.

Previously api_mark_all_read looped with no batch/time budget and only
checked for a None cursor: a non-advancing cursor would spin forever, and
an exception mid-loop left earlier batches committed with no signal.
Now: a max-batch and max-duration budget, a non-advancing cursor errors
out, and the endpoint documents that it is non-atomic but idempotent.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from mail_core.api import mail as mail_api
from mail_core.api.mail import MarkAllReadBody
from mail_core.mail.application.mutations import MARK_ALL_READ_BATCH_SIZE, MarkAllReadBatchResult


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def commit(self):
        pass


def _patch_common(monkeypatch):
    monkeypatch.setattr(mail_api, "get_session_factory", lambda: _Session)
    monkeypatch.setattr(mail_api, "enabled_account_ids", lambda _session: [])


def _full_batch(n: int) -> MarkAllReadBatchResult:
    return MarkAllReadBatchResult(MARK_ALL_READ_BATCH_SIZE, uuid.UUID(int=n))


def test_batch_budget_bounds_the_loop(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(mail_api, "MARK_ALL_READ_MAX_BATCHES", 3)
    calls = {"n": 0}

    def fake(_session, **_kwargs):
        calls["n"] += 1
        return _full_batch(calls["n"])

    monkeypatch.setattr(mail_api, "mark_all_messages_read", fake)

    with pytest.raises(HTTPException) as excinfo:
        mail_api.api_mark_all_read(MarkAllReadBody())

    assert calls["n"] == 3
    assert "retr" in str(excinfo.value.detail).lower()  # retry guidance


def test_time_budget_bounds_the_loop(monkeypatch):
    _patch_common(monkeypatch)
    monkeypatch.setattr(mail_api, "MARK_ALL_READ_MAX_SECONDS", 0.0)
    calls = {"n": 0}

    def fake(_session, **_kwargs):
        calls["n"] += 1
        return _full_batch(calls["n"])

    monkeypatch.setattr(mail_api, "mark_all_messages_read", fake)

    with pytest.raises(HTTPException):
        mail_api.api_mark_all_read(MarkAllReadBody())
    assert calls["n"] == 0


def test_non_advancing_cursor_errors_out(monkeypatch):
    _patch_common(monkeypatch)
    stuck = uuid.UUID(int=42)
    monkeypatch.setattr(
        mail_api,
        "mark_all_messages_read",
        lambda _session, **_kwargs: MarkAllReadBatchResult(MARK_ALL_READ_BATCH_SIZE, stuck),
    )

    with pytest.raises(HTTPException) as excinfo:
        mail_api.api_mark_all_read(MarkAllReadBody())
    assert "cursor" in str(excinfo.value.detail).lower()


def test_normal_completion_still_works(monkeypatch):
    _patch_common(monkeypatch)
    batches = iter([_full_batch(1), MarkAllReadBatchResult(7, uuid.UUID(int=2))])
    monkeypatch.setattr(mail_api, "mark_all_messages_read", lambda _s, **_k: next(batches))

    result = mail_api.api_mark_all_read(MarkAllReadBody())

    assert result.count == MARK_ALL_READ_BATCH_SIZE + 7
    assert result.success is True
