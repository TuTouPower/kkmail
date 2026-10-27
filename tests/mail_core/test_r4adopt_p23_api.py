"""R4 adoption P23 (API wave): A103 / A163 / A201 regression tests."""

from __future__ import annotations

import uuid
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from mail_core.mail.application.accounts import AccountDTO


def _dto(email: str = "new@kkmail.test") -> AccountDTO:
    return AccountDTO(
        id=str(uuid.uuid4()),
        email=email,
        provider="imap",
        display_name="New Account",
        group_id=None,
        group_name=None,
        group_color=None,
        status="active",
        sync_status="idle",
        sync_enabled=True,
        account_type="imap",
        remark=None,
    )


# --- A163: sync endpoints must 404 (not 500) when the report is gone ---


class _DummySession:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def commit(self):
        return None


def _patch_sync_route(monkeypatch, module, report):
    req = Mock()
    req.id = uuid.uuid4()
    monkeypatch.setattr(module, "get_session_factory", lambda: lambda: _DummySession())
    monkeypatch.setattr(module, "create_sync_request", Mock(return_value=(req, True)))
    monkeypatch.setattr(module, "get_sync_request_report", Mock(return_value=report))
    return req


def test_sync_account_report_none_is_404(monkeypatch):
    from fastapi import HTTPException

    import mail_core.api.accounts as accounts_api

    _patch_sync_route(monkeypatch, accounts_api, None)
    with pytest.raises(HTTPException) as excinfo:
        accounts_api.api_sync_account(uuid.uuid4())
    assert excinfo.value.status_code == 404


def test_sync_all_report_none_is_404(monkeypatch):
    from fastapi import HTTPException

    import mail_core.api.accounts as accounts_api

    _patch_sync_route(monkeypatch, accounts_api, None)
    with pytest.raises(HTTPException) as excinfo:
        accounts_api.api_sync_all_accounts()
    assert excinfo.value.status_code == 404


def test_sync_delta_report_none_is_404(monkeypatch):
    from fastapi import HTTPException, Response

    import mail_core.api.mail as mail_api

    _patch_sync_route(monkeypatch, mail_api, None)
    body = mail_api.DeltaSyncIn(account_id=uuid.uuid4())
    with pytest.raises(HTTPException) as excinfo:
        mail_api.api_sync_delta(body, Response())
    assert excinfo.value.status_code == 404


# --- A103: production API must not create memory/stub test-provider accounts ---


@pytest.mark.parametrize("provider", ["memory", "stub"])
def test_create_account_rejects_test_providers_by_default(api_client, monkeypatch, provider):
    monkeypatch.delenv("MAIL_CORE_ALLOW_TEST_PROVIDERS", raising=False)
    create = Mock(return_value=_dto())
    monkeypatch.setattr("mail_core.api.accounts.create_account_app", create)

    response = api_client.post(
        "/api/accounts",
        json={"email": "new@kkmail.test", "provider": provider},
    )

    assert response.status_code == 422
    create.assert_not_called()


def test_account_create_model_rejects_test_providers_by_default(monkeypatch):
    from mail_core.api.accounts import AccountCreateIn

    monkeypatch.delenv("MAIL_CORE_ALLOW_TEST_PROVIDERS", raising=False)
    with pytest.raises(ValidationError):
        AccountCreateIn(email="new@kkmail.test", provider="memory")
    with pytest.raises(ValidationError):
        AccountCreateIn(email="new@kkmail.test", provider="stub")
    # Production providers remain accepted.
    assert AccountCreateIn(email="a@ex.com", provider="imap").provider == "imap"
    assert AccountCreateIn(email="a@ex.com", provider="graph").provider == "graph"


def test_create_account_allows_test_providers_only_with_env_switch(api_client, monkeypatch):
    monkeypatch.setenv("MAIL_CORE_ALLOW_TEST_PROVIDERS", "1")
    with patch("mail_core.api.accounts.create_account_app", return_value=_dto()):
        response = api_client.post(
            "/api/accounts",
            json={"email": "new@kkmail.test", "provider": "memory"},
        )
    assert response.status_code == 200, response.text
