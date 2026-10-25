from __future__ import annotations

from uuid import uuid4

import pytest

from mail_core.api import mail as mail_api
from mail_core.api.mail import MarkAllReadBody
from mail_core.mail.application.mutations import MarkAllReadBatchResult


class _Session:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def commit(self):
        pass


_account_body = MarkAllReadBody(account_id=uuid4())
_group_body = MarkAllReadBody(group_id=uuid4())
_folder_body = MarkAllReadBody(folder_id=uuid4())
_group_account_ids = [uuid4()]


@pytest.mark.parametrize(
    ("body", "group_account_ids", "scope_type", "scope_id", "expected_kwargs"),
    [
        (
            MarkAllReadBody(),
            None,
            "global",
            None,
            {"account_id": None, "group_id": None, "account_ids": None, "folder_id": None},
        ),
        (
            _account_body,
            None,
            "account",
            str(_account_body.account_id),
            {
                "account_id": _account_body.account_id,
                "group_id": None,
                "account_ids": None,
                "folder_id": None,
            },
        ),
        (
            _group_body,
            _group_account_ids,
            "group",
            str(_group_body.group_id),
            {
                "account_id": None,
                "group_id": None,
                "account_ids": _group_account_ids,
                "folder_id": None,
            },
        ),
        (
            _folder_body,
            None,
            "folder",
            str(_folder_body.folder_id),
            {
                "account_id": None,
                "group_id": None,
                "account_ids": None,
                "folder_id": _folder_body.folder_id,
            },
        ),
    ],
)
def test_mark_all_read_response_reports_effective_scope(
    monkeypatch, body, group_account_ids, scope_type, scope_id, expected_kwargs
):
    captured = {}
    monkeypatch.setattr(mail_api, "get_session_factory", lambda: _Session)
    monkeypatch.setattr(
        mail_api,
        "mark_all_messages_read",
        lambda _session, **kwargs: captured.update(kwargs) or MarkAllReadBatchResult(0, None),
    )
    if body.group_id is not None:
        monkeypatch.setattr(
            mail_api,
            "account_ids_for_group",
            lambda _session, _group_id: group_account_ids,
        )

    result = mail_api.api_mark_all_read(body)

    assert result.scope_type == scope_type
    assert result.scope_id == scope_id
    assert result.account_id == (str(body.account_id) if body.account_id else None)
    for key, expected_value in expected_kwargs.items():
        assert captured[key] == expected_value
