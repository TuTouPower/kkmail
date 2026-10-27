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
