"""Account API auth gate (no DB required for 401)."""

import logging

import pytest
from fastapi.testclient import TestClient

from mail_core.api.app import app


def test_accounts_require_auth():
    client = TestClient(app)
    assert client.get("/api/accounts").status_code == 401
    assert client.get("/api/groups").status_code == 401
    assert client.get("/api/settings").status_code == 401


def test_account_create_validation_constraints(api_client):
    from mail_core.api.accounts import _has_basic_email_shape

    assert _has_basic_email_shape("user@localhost")
    assert not _has_basic_email_shape("not-an-email")

    invalid_memory_email = api_client.post(
        "/api/accounts",
        json={"email": "not-an-email", "provider": "memory"},
    )
    assert invalid_memory_email.status_code == 422

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


def test_account_status_is_derived_from_sync_enabled():
    # A234: replaces test_account_status_remains_active_when_sync_is_disabled
    # overall — that test enshrined the hard-coded status="active" bug.
    # New contract: status is derived from the account's real state —
    # "disabled" when sync is disabled, "active" when sync is enabled —
    # while sync_status keeps carrying the detailed sync state.
    from types import SimpleNamespace
    import uuid

    from mail_core.mail.application.accounts import _to_account_dto

    def make_account(*, sync_enabled, sync_status="idle"):
        return SimpleNamespace(
            id=uuid.uuid4(),
            email="derived@kkmail.test",
            provider="imap",
            display_name=None,
            group_id=None,
            master_order=None,
            group_order=None,
            sync_enabled=sync_enabled,
            sync_status=sync_status,
            config={},
        )

    disabled = _to_account_dto(make_account(sync_enabled=False), {})
    assert disabled.status == "disabled"
    assert disabled.sync_enabled is False

    enabled = _to_account_dto(make_account(sync_enabled=True, sync_status="failed"), {})
    assert enabled.status == "active"
    assert enabled.sync_status == "failed"


def _sync_all_fake_session(pages):
    """Fake session serving keyset pages (lists of account UUIDs) in order."""
    import uuid

    class Session:
        def __init__(self):
            self.commits = 0
            self.rollbacks = 0
            self.statements = []
            self._pages = [list(page) for page in pages]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, stmt):
            self.statements.append(stmt)
            page = self._pages.pop(0) if self._pages else []

            class _Scalars:
                def __init__(self, rows):
                    self._rows = rows

                def all(self):
                    return list(self._rows)

                def __iter__(self):
                    return iter(self._rows)

            return _Scalars(page)

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    return Session()


def test_sync_all_keyset_collects_then_enqueues_in_single_commit(monkeypatch):
    # A114: replaces the former per-page-commit expectation overall — the old
    # test asserted 3 commits for 3 offset pages, which is exactly the
    # partial-enqueue bug being fixed. New contract: keyset (id cursor)
    # collection of every sync-enabled account id first, then all enqueues
    # in one transaction with a single commit (all-or-nothing).
    import uuid

    import mail_core.mail.application.accounts as accounts_app

    ids = [uuid.UUID(int=index + 1) for index in range(105)]
    pages = [ids[:50], ids[50:100], ids[100:]]
    session = _sync_all_fake_session(pages)
    enqueued = []

    def enqueue(_session, account_id):
        enqueued.append(account_id)
        return uuid.UUID(int=account_id.int + 1_000)

    monkeypatch.setattr(accounts_app, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(accounts_app, "enqueue_account_sync", enqueue)

    result = accounts_app.sync_all_accounts_app(page_size=50)

    assert enqueued == ids
    assert result.count == 105
    assert result.job_ids == [str(uuid.UUID(int=i + 1_000)) for i in range(1, 101)]
    assert session.commits == 1
    assert session.rollbacks == 0
    # Keyset pagination: later pages filter on the id cursor, never OFFSET.
    assert len(session.statements) == 3
    rendered = [str(stmt) for stmt in session.statements]
    assert all("OFFSET" not in sql.upper() for sql in rendered)
    assert "sync_enabled" in rendered[0]
    assert "accounts.id >" in rendered[1]
    assert "accounts.id >" in rendered[2]


def test_sync_all_enqueue_failure_rolls_back_without_any_commit(monkeypatch):
    import uuid

    import pytest

    import mail_core.mail.application.accounts as accounts_app

    ids = [uuid.UUID(int=index + 1) for index in range(3)]
    session = _sync_all_fake_session([ids])

    def enqueue(_session, account_id):
        if account_id == ids[1]:
            raise RuntimeError("enqueue boom")
        return uuid.UUID(int=account_id.int + 1_000)

    monkeypatch.setattr(accounts_app, "get_session_factory", lambda: lambda: session)
    monkeypatch.setattr(accounts_app, "enqueue_account_sync", enqueue)

    with pytest.raises(RuntimeError, match="enqueue boom"):
        accounts_app.sync_all_accounts_app(page_size=50)

    assert session.commits == 0
    assert session.rollbacks == 1


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


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (PermissionError("not allowed"), 403),
        (LookupError("missing resource"), 404),
        (ValueError("invalid account configuration"), 400),
    ],
)
def test_create_account_maps_known_errors(api_client, monkeypatch, error, status_code):
    from unittest.mock import Mock

    # "memory" is a test-only provider since A103; this test uses it as a
    # neutral fixture provider, so opt in via the environment switch.
    monkeypatch.setenv("MAIL_CORE_ALLOW_TEST_PROVIDERS", "1")
    monkeypatch.setattr("mail_core.api.accounts.create_account_app", Mock(side_effect=error))
    response = api_client.post(
        "/api/accounts",
        json={"email": "new@kkmail.test", "provider": "memory"},
    )

    assert response.status_code == status_code
    assert response.json()["detail"] == str(error)


def test_create_account_hides_and_safely_logs_unexpected_errors(api_client, monkeypatch, caplog):
    from unittest.mock import Mock

    # See test_create_account_maps_known_errors: test-provider opt-in (A103).
    monkeypatch.setenv("MAIL_CORE_ALLOW_TEST_PROVIDERS", "1")
    monkeypatch.setattr(
        "mail_core.api.accounts.create_account_app",
        Mock(side_effect=RuntimeError("password=private-secret")),
    )
    with caplog.at_level(logging.ERROR, logger="mail_core.api.accounts"):
        response = api_client.post(
            "/api/accounts",
            json={"email": "new@kkmail.test", "provider": "memory"},
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "internal server error"}
    assert "account creation failed" in caplog.text
    assert "password=[REDACTED]" in caplog.text
    assert "private-secret" not in caplog.text


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


def test_account_update_passes_explicit_credential_clear_list(api_client, monkeypatch):
    import uuid
    from unittest.mock import Mock

    from mail_core.mail.application.accounts import AccountDTO

    account_id = uuid.uuid4()
    dto = AccountDTO(
        id=str(account_id),
        email="oauth@kkmail.test",
        provider="graph",
        display_name=None,
        group_id=None,
        group_name=None,
        group_color=None,
        status="active",
        sync_status="idle",
        sync_enabled=True,
        account_type="graph",
        remark=None,
    )
    update = Mock(return_value=dto)
    monkeypatch.setattr("mail_core.api.accounts.update_account_app", update)

    response = api_client.patch(
        f"/api/accounts/{account_id}",
        json={"clear_credentials": ["client_secret"]},
    )

    assert response.status_code == 200, response.text
    assert update.call_args.kwargs["clear_credentials"] == ["client_secret"]
