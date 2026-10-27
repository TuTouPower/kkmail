"""Account / group / settings / sync-trigger HTTP API."""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import asdict
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field, field_validator, field_serializer

from mail_core.accounts import StaleSidebarLayoutError
from mail_core.api.deps import require_auth
from mail_core.db.session import get_session_factory
from mail_core.mail.application.sync_requests import (
    SyncRequestOut,
    create_sync_request,
    get_sync_request_report,
)
from mail_core.security.auth import AuthPrincipal
from mail_core.security.redact import safe_error
from mail_core.mail.application.accounts import (
    create_account_app,
    create_group_app,
    delete_account_app,
    delete_group_app,
    get_sidebar_layout_app,
    get_settings_app,
    list_accounts_app,
    list_groups_app,
    rename_group_app,
    reset_sidebar_account_order_app,
    save_sidebar_layout_app,
    sync_account_app,
    sync_all_accounts_app,
    update_account_app,
    update_settings_app,
)

router = APIRouter(tags=["accounts"])
log = logging.getLogger("mail_core.api.accounts")


class ImapConfigOut(BaseModel):
    imap_host: str | None = None
    imap_user: str | None = None
    imap_port: int | None = None
    use_ssl: bool | None = None


class AccountOut(BaseModel):
    id: str
    email: str
    provider: str
    display_name: str | None = None
    group_id: str | None = None
    group_name: str | None = None
    group_color: str | None = None
    master_order: int | None = None
    group_order: int | None = None
    status: str
    sync_status: str
    sync_enabled: bool
    account_type: str
    remark: str | None = None
    imap_config: ImapConfigOut | None = None
    provider_profile: str | None = None
    oauth_client_type: str | None = None
    oauth_tenant: str | None = None
    recipient_addresses: list[str] = Field(default_factory=list)

    @field_serializer("imap_config")
    def serialize_imap_config(self, value):
        if value is None:
            return None
        return {key: item for key, item in value.model_dump().items() if key != "imap_user" or item is not None}


class AccountsPage(BaseModel):
    accounts: list[AccountOut]
    total: int
    limit: int
    offset: int
    has_more: bool


AllowedProvider = Literal["imap", "graph"]

#: Test-only providers backed by in-memory stubs. They must never be
#: creatable through the production API; test fixtures opt in explicitly
#: via the MAIL_CORE_ALLOW_TEST_PROVIDERS environment switch (A103).
TestProvider = Literal["memory", "stub"]
_TEST_PROVIDERS = ("memory", "stub")


def test_providers_allowed() -> bool:
    return os.environ.get("MAIL_CORE_ALLOW_TEST_PROVIDERS", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _has_basic_email_shape(email: str) -> bool:
    if email.count("@") != 1:
        return False
    local_part, domain = email.split("@", 1)
    return bool(local_part and domain and not any(character.isspace() for character in email))


class AccountCreateIn(BaseModel):
    email: str = Field(default="", max_length=320)
    provider: str

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        allowed: tuple[str, ...] = ("imap", "graph")
        if test_providers_allowed():
            allowed = allowed + _TEST_PROVIDERS
        if value not in allowed:
            raise ValueError(f"provider must be one of {sorted(allowed)}")
        return value
    display_name: str | None = Field(default=None, max_length=255)
    group_id: UUID | None = None
    config: dict[str, Any] | None = None
    # Written to credential store; never returned.
    credentials: dict[str, Any] | None = None
    oauth_flow_id: str | None = Field(default=None, max_length=128)


class AccountUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=255)
    group_id: UUID | None = None
    clear_group: bool = False
    sync_enabled: bool | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None
    clear_credentials: list[str] = Field(
        default_factory=list,
        description="Credential fields to remove explicitly; empty values in credentials still preserve stored values.",
    )
    oauth_flow_id: str | None = Field(default=None, max_length=128)


class GroupOut(BaseModel):
    id: str
    name: str
    color: str | None = None
    account_count: int = 0
    sort_order: int = 0


class GroupCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    color: str | None = Field(default=None, max_length=32)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class GroupUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)

    @field_validator("name", mode="before")
    @classmethod
    def strip_name(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


_SIDEBAR_MAX_GROUPS = 1000
_SIDEBAR_MAX_ACCOUNTS = 5000


class SidebarLayoutIn(BaseModel):
    group_ids: list[UUID] = Field(max_length=_SIDEBAR_MAX_GROUPS)
    master_account_ids: list[UUID] = Field(max_length=_SIDEBAR_MAX_ACCOUNTS)
    ungrouped_account_ids: list[UUID] = Field(max_length=_SIDEBAR_MAX_ACCOUNTS)
    group_account_ids: dict[UUID, list[UUID]] = Field(max_length=_SIDEBAR_MAX_GROUPS)
    expected_revision: str = Field(min_length=64, max_length=64)

    @field_validator("group_account_ids")
    @classmethod
    def bound_group_account_ids(cls, value: dict[UUID, list[UUID]]) -> dict[UUID, list[UUID]]:
        if sum(len(account_ids) for account_ids in value.values()) > _SIDEBAR_MAX_ACCOUNTS:
            raise ValueError(f"group account lists must not exceed {_SIDEBAR_MAX_ACCOUNTS} accounts in total")
        return value


class SidebarLayoutRevisionIn(BaseModel):
    expected_revision: str = Field(min_length=64, max_length=64)


class SidebarLayoutSnapshotOut(BaseModel):
    revision: str
    group_ids: list[UUID]
    master_account_ids: list[UUID]
    ungrouped_account_ids: list[UUID]
    group_account_ids: dict[UUID, list[UUID]]


class GroupsOut(BaseModel):
    groups: list[GroupOut]


class SyncJobOut(BaseModel):
    job_id: str


class SyncAllOut(BaseModel):
    job_ids: list[str]
    count: int


class SettingsOut(BaseModel):
    settings: dict[str, str]


_SETTINGS_MAX_KEYS = 100
_SETTINGS_MAX_KEY_LENGTH = 128
_SETTINGS_MAX_VALUE_LENGTH = 4096


class SettingsUpdateIn(BaseModel):
    """Public settings patch. Unknown / secret keys are rejected by the service."""

    settings: dict[str, str] = Field(default_factory=dict, max_length=_SETTINGS_MAX_KEYS)

    @field_validator("settings")
    @classmethod
    def bound_settings(cls, value: dict[str, str]) -> dict[str, str]:
        if any(len(key) > _SETTINGS_MAX_KEY_LENGTH for key in value):
            raise ValueError(f"setting keys must not exceed {_SETTINGS_MAX_KEY_LENGTH} characters")
        if any(len(item) > _SETTINGS_MAX_VALUE_LENGTH for item in value.values()):
            raise ValueError(f"setting values must not exceed {_SETTINGS_MAX_VALUE_LENGTH} characters")
        return value


@router.get("/api/accounts", response_model=AccountsPage)
def api_list_accounts(
    group_id: UUID | None = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    page = list_accounts_app(group_id=group_id, limit=limit, offset=offset)
    return AccountsPage(
        accounts=[AccountOut(**asdict(a)) for a in page.accounts],
        total=page.total,
        limit=page.limit,
        offset=page.offset,
        has_more=page.has_more,
    )


@router.post("/api/accounts", response_model=AccountOut)
def api_create_account(body: AccountCreateIn, principal: AuthPrincipal = Depends(require_auth)):
    email = (body.email or "").strip()
    if not body.oauth_flow_id:
        if len(email) < 3:
            raise HTTPException(422, "email must have at least 3 characters")
        if not _has_basic_email_shape(email):
            raise HTTPException(422, "email must have a valid address shape")
    try:
        from mail_core.accounts.connection import validate_connection, merge_credentials
        if not body.oauth_flow_id and body.provider in ("imap", "graph"):
            cleaned = merge_credentials(body.provider, {}, body.credentials or {})
            validate_connection(email, body.provider, body.config or {}, cleaned)
        acc = create_account_app(
            email=email,
            provider=body.provider,
            display_name=body.display_name,
            group_id=body.group_id,
            config=body.config,
            credentials=body.credentials,
            oauth_flow_id=body.oauth_flow_id,
            principal=principal,
        )
        return AccountOut(**asdict(acc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        log.error("account creation failed: %s", safe_error(exc))
        raise HTTPException(500, "internal server error") from None


@router.patch("/api/accounts/{account_id}", response_model=AccountOut)
def api_update_account(account_id: UUID, body: AccountUpdateIn, principal: AuthPrincipal = Depends(require_auth)):
    try:
        acc = update_account_app(
            account_id,
            display_name=body.display_name,
            group_id=body.group_id,
            clear_group=body.clear_group,
            sync_enabled=body.sync_enabled,
            config=body.config,
            credentials=body.credentials,
            clear_credentials=body.clear_credentials,
            oauth_flow_id=body.oauth_flow_id,
            principal=principal,
        )
        return AccountOut(**asdict(acc))
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/api/accounts/{account_id}", status_code=204, response_class=Response)
def api_delete_account(account_id: UUID) -> Response:
    try:
        delete_account_app(account_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(status_code=204)


@router.post("/api/accounts/{account_id}/sync", response_model=SyncRequestOut, status_code=202)
def api_sync_account(account_id: UUID) -> SyncRequestOut:
    Session = get_session_factory()
    client_req_id = uuid.uuid4().hex
    with Session() as session:
        try:
            req, _ = create_sync_request(
                session,
                client_request_id=client_req_id,
                mode="full",
                trigger="manual",
                scope={"account_id": str(account_id)},
                account_id=account_id,
            )
            req_id = req.id
            session.commit()
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    with Session() as session:
        return get_sync_request_report(session, req_id)  # type: ignore[return-value]


@router.post("/api/accounts/sync-all", response_model=SyncRequestOut, status_code=202)
def api_sync_all_accounts() -> SyncRequestOut:
    Session = get_session_factory()
    client_req_id = uuid.uuid4().hex
    with Session() as session:
        req, _ = create_sync_request(
            session,
            client_request_id=client_req_id,
            mode="full",
            trigger="manual",
            scope={"all": True},
        )
        req_id = req.id
        session.commit()

    with Session() as session:
        return get_sync_request_report(session, req_id)  # type: ignore[return-value]


@router.get("/api/groups", response_model=GroupsOut)
def api_list_groups() -> GroupsOut:
    groups = list_groups_app()
    return GroupsOut(
        groups=[
            GroupOut(id=g.id, name=g.name, color=g.color, account_count=g.account_count, sort_order=g.sort_order)
            for g in groups
        ]
    )


@router.post("/api/groups", response_model=GroupOut)
def api_create_group(body: GroupCreateIn) -> GroupOut:
    try:
        g = create_group_app(name=body.name, color=body.color)
        return GroupOut(id=g.id, name=g.name, color=g.color, account_count=0, sort_order=g.sort_order)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.patch("/api/groups/{group_id}", response_model=GroupOut)
def api_rename_group(group_id: UUID, body: GroupUpdateIn) -> GroupOut:
    try:
        group = rename_group_app(group_id, name=body.name)
        return GroupOut(
            id=group.id,
            name=group.name,
            color=group.color,
            account_count=group.account_count,
            sort_order=group.sort_order,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/sidebar/layout", response_model=SidebarLayoutSnapshotOut)
def api_get_sidebar_layout() -> SidebarLayoutSnapshotOut:
    return SidebarLayoutSnapshotOut(**get_sidebar_layout_app())


@router.put(
    "/api/sidebar/layout",
    status_code=204,
    response_class=Response,
    responses={409: {"description": "The sidebar layout changed after the supplied revision was read."}},
)
def api_save_sidebar_layout(body: SidebarLayoutIn) -> Response:
    try:
        save_sidebar_layout_app(
            expected_revision=body.expected_revision,
            group_ids=body.group_ids,
            master_account_ids=body.master_account_ids,
            ungrouped_account_ids=body.ungrouped_account_ids,
            group_account_ids=body.group_account_ids,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except StaleSidebarLayoutError as exc:
        raise HTTPException(409, "sidebar layout changed; reload and retry") from exc
    return Response(status_code=204)


@router.post(
    "/api/sidebar/layout/default-order",
    status_code=204,
    response_class=Response,
    responses={409: {"description": "The sidebar layout changed after the supplied revision was read."}},
)
def api_reset_sidebar_account_order(body: SidebarLayoutRevisionIn) -> Response:
    try:
        reset_sidebar_account_order_app(expected_revision=body.expected_revision)
    except StaleSidebarLayoutError as exc:
        raise HTTPException(409, "sidebar layout changed; reload and retry") from exc
    return Response(status_code=204)


@router.delete("/api/groups/{group_id}", status_code=204, response_class=Response)
def api_delete_group(group_id: UUID) -> Response:
    try:
        delete_group_app(group_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(status_code=204)


@router.get("/api/settings", response_model=SettingsOut)
def api_get_settings() -> SettingsOut:
    res = get_settings_app()
    return SettingsOut(settings=res.settings)


@router.put("/api/settings", response_model=SettingsOut)
def api_update_settings(body: SettingsUpdateIn) -> SettingsOut:
    try:
        res = update_settings_app(body.settings)
        return SettingsOut(settings=res.settings)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
