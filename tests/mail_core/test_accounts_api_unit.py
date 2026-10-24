"""Account API auth gate (no DB required for 401)."""

from fastapi.testclient import TestClient

from mail_core.api.app import app


def test_accounts_require_auth():
    client = TestClient(app)
    assert client.get("/api/accounts").status_code == 401
    assert client.get("/api/groups").status_code == 401
    assert client.get("/api/settings").status_code == 401


def test_account_create_validation_constraints(api_client):
    # Invalid provider
    res = api_client.post("/api/accounts", json={"email": "a@ex.com", "provider": "invalid_provider"})
    assert res.status_code == 422

    # display_name too long (> 255)
    res = api_client.post(
        "/api/accounts",
        json={"email": "a@ex.com", "provider": "imap", "display_name": "x" * 256},
    )
    assert res.status_code == 422


def test_account_update_validation_constraints(api_client):
    # display_name too long (> 255)
    res = api_client.patch(
        "/api/accounts/00000000-0000-0000-0000-000000000001",
        json={"display_name": "x" * 256},
    )
    assert res.status_code == 422


def test_group_create_validation_constraints(api_client):
    # color too long (> 32)
    res = api_client.post("/api/groups", json={"name": "Work", "color": "c" * 33})
    assert res.status_code == 422


def test_group_names_are_trimmed_before_length_validation():
    import pytest
    from pydantic import ValidationError

    from mail_core.api.accounts import GroupCreateIn, GroupUpdateIn

    normalized = "x" * 128
    assert GroupCreateIn(name=f" {normalized} ").name == normalized
    assert GroupUpdateIn(name=f" {normalized} ").name == normalized
    with pytest.raises(ValidationError):
        GroupCreateIn(name=f" {normalized}x ")
    with pytest.raises(ValidationError):
        GroupUpdateIn(name="   ")


def test_list_accounts_serializes_slotted_dtos_mock(api_client):
    import uuid
    from unittest.mock import patch
    from mail_core.mail.application.accounts import AccountDTO, AccountPageDTO

    acc_id = str(uuid.uuid4())
    dto = AccountDTO(
        id=acc_id,
        email="user@kkmail.test",
        provider="imap",
        display_name="User Test",
        group_id=None,
        group_name=None,
        group_color=None,
        status="active",
        sync_status="idle",
        sync_enabled=True,
        account_type="imap",
        remark="test remark",
        imap_config={"imap_host": "imap.kkmail.test", "imap_port": 993, "use_ssl": True},
    )
    mock_page = AccountPageDTO(accounts=[dto], total=1, limit=200, offset=0, has_more=False)

    with patch("mail_core.api.accounts.list_accounts_app", return_value=mock_page):
        res = api_client.get("/api/accounts")
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["total"] == 1
        assert len(data["accounts"]) == 1
        acc = data["accounts"][0]
        assert acc["id"] == acc_id
        assert acc["email"] == "user@kkmail.test"
        assert acc["provider"] == "imap"
        assert acc["display_name"] == "User Test"
        assert acc["remark"] == "test remark"
        assert acc["imap_config"] == {"imap_host": "imap.kkmail.test", "imap_port": 993, "use_ssl": True}
        assert "credentials" not in acc


def test_account_dto_exposes_only_supported_imap_connection_fields():
    from types import SimpleNamespace
    import uuid

    from mail_core.mail.application.accounts import _to_account_dto

    account = SimpleNamespace(
        id=uuid.uuid4(),
        email="user@kkmail.test",
        provider="imap",
        display_name=None,
        group_id=None,
        master_order=None,
        group_order=None,
        sync_enabled=True,
        sync_status="idle",
        config={
            "imap_host": "imap.kkmail.test",
            "imap_port": "143",
            "use_ssl": "false",
            "last_sync_error": "internal status",
            "password": "must not be returned",
        },
    )

    dto = _to_account_dto(account, {})
    assert dto.imap_config == {"imap_host": "imap.kkmail.test", "imap_port": 143, "use_ssl": False}
    assert "last_sync_error" not in dto.imap_config
    assert "password" not in dto.imap_config


def test_create_account_serializes_slotted_dto_mock(api_client):
    import uuid
    from unittest.mock import patch
    from mail_core.mail.application.accounts import AccountDTO

    acc_id = str(uuid.uuid4())
    dto = AccountDTO(
        id=acc_id,
        email="new@kkmail.test",
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

    with patch("mail_core.api.accounts.create_account_app", return_value=dto):
        res = api_client.post("/api/accounts", json={"email": "new@kkmail.test", "provider": "imap", "config": {"imap_host": "imap.kkmail.test"}, "credentials": {"password": "test-password"}})
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["id"] == acc_id
        assert data["email"] == "new@kkmail.test"


def test_update_account_serializes_slotted_dto_mock(api_client):
    import uuid
    from unittest.mock import patch
    from mail_core.mail.application.accounts import AccountDTO

    acc_id = uuid.uuid4()
    dto = AccountDTO(
        id=str(acc_id),
        email="updated@kkmail.test",
        provider="imap",
        display_name="Updated Account",
        group_id=None,
        group_name=None,
        group_color=None,
        status="active",
        sync_status="idle",
        sync_enabled=True,
        account_type="imap",
        remark=None,
    )

    with patch("mail_core.api.accounts.update_account_app", return_value=dto):
        res = api_client.patch(f"/api/accounts/{acc_id}", json={"display_name": "Updated Account"})
        assert res.status_code == 200, res.text
        data = res.json()
        assert data["id"] == str(acc_id)
        assert data["display_name"] == "Updated Account"
