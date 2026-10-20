"""Account / group / settings / sync-trigger HTTP API."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field

from mail_core.accounts import (
    create_account,
    create_group,
    delete_account,
    delete_group,
    enqueue_account_sync,
    get_public_settings,
    list_accounts,
    list_groups,
    update_account,
    update_public_settings,
)
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import Account, AccountGroup

router = APIRouter(tags=["accounts"])


class AccountOut(BaseModel):
    id: str
    email: str
    provider: str
    display_name: str | None = None
    group_id: str | None = None
    group_name: str | None = None
    group_color: str | None = None
    status: str
    sync_status: str
    sync_enabled: bool
    account_type: str
    remark: str | None = None


class AccountsPage(BaseModel):
    accounts: list[AccountOut]
    total: int
    limit: int
    offset: int
    has_more: bool


class AccountCreateIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    provider: str = Field(min_length=2, max_length=32)
    display_name: str | None = None
    group_id: UUID | None = None
    config: dict[str, Any] | None = None
    # Written to credential store; never returned.
    credentials: dict[str, Any] | None = None


class AccountUpdateIn(BaseModel):
    display_name: str | None = None
    group_id: UUID | None = None
    clear_group: bool = False
    sync_enabled: bool | None = None
    config: dict[str, Any] | None = None
    credentials: dict[str, Any] | None = None


class GroupOut(BaseModel):
    id: str
    name: str
    color: str | None = None
    account_count: int = 0


class GroupCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    color: str | None = None


class GroupsOut(BaseModel):
    groups: list[GroupOut]


class SyncJobOut(BaseModel):
    job_id: str


class SyncAllOut(BaseModel):
    job_ids: list[str]
    count: int


class SettingsOut(BaseModel):
    settings: dict[str, str]


class SettingsUpdateIn(BaseModel):
    """Public settings patch. Unknown / secret keys are rejected by the service."""

    settings: dict[str, str] = Field(default_factory=dict)


def _account_out(acc: Account, groups: dict[UUID, AccountGroup]) -> AccountOut:
    g = groups.get(acc.group_id) if acc.group_id else None
    remark = None
    if isinstance(acc.config, dict):
        remark = acc.config.get("remark")
        if remark is not None:
            remark = str(remark)
    return AccountOut(
        id=str(acc.id),
        email=acc.email,
        provider=acc.provider,
        display_name=acc.display_name,
        group_id=str(acc.group_id) if acc.group_id else None,
        group_name=g.name if g else None,
        group_color=g.color if g else None,
        status="active" if acc.sync_enabled else "disabled",
        sync_status=acc.sync_status,
        sync_enabled=acc.sync_enabled,
        account_type=acc.provider,
        remark=remark,
    )


@router.get("/api/accounts", response_model=AccountsPage)
def api_list_accounts(
    group_id: UUID | None = None,
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    Session = get_session_factory()
    with Session() as session:
        rows, total = list_accounts(session, group_id=group_id, limit=limit, offset=offset)
        gmap = {g.id: g for g, _n in list_groups(session)}
        items = [_account_out(a, gmap) for a in rows]
        return AccountsPage(
            accounts=items,
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + len(items) < total,
        )


@router.post("/api/accounts", response_model=AccountOut)
def api_create_account(body: AccountCreateIn):
    Session = get_session_factory()
    with Session() as session:
        try:
            acc = create_account(
                session,
                email=body.email,
                provider=body.provider,
                display_name=body.display_name,
                group_id=body.group_id,
                config=body.config,
                credentials=body.credentials,
            )
            session.commit()
        except Exception as exc:
            session.rollback()
            raise HTTPException(400, str(exc)) from exc
        gmap = {g.id: g for g, _n in list_groups(session)}
        return _account_out(acc, gmap)


@router.patch("/api/accounts/{account_id}", response_model=AccountOut)
def api_update_account(account_id: UUID, body: AccountUpdateIn):
    Session = get_session_factory()
    with Session() as session:
        try:
            group_arg: object = ...
            if body.clear_group:
                group_arg = None
            elif body.group_id is not None:
                group_arg = body.group_id
            acc = update_account(
                session,
                account_id,
                display_name=body.display_name,
                group_id=group_arg,
                sync_enabled=body.sync_enabled,
                config_patch=body.config,
                credentials=body.credentials,
            )
            session.commit()
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        gmap = {g.id: g for g, _n in list_groups(session)}
        return _account_out(acc, gmap)


@router.delete("/api/accounts/{account_id}", status_code=204, response_class=Response)
def api_delete_account(account_id: UUID) -> Response:
    Session = get_session_factory()
    with Session() as session:
        try:
            delete_account(session, account_id)
            session.commit()
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
    return Response(status_code=204)


@router.post("/api/accounts/{account_id}/sync", response_model=SyncJobOut)
def api_sync_account(account_id: UUID) -> SyncJobOut:
    Session = get_session_factory()
    with Session() as session:
        try:
            job_id = enqueue_account_sync(session, account_id)
            session.commit()
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
    return SyncJobOut(job_id=str(job_id))


_SYNC_ALL_PAGE = 500


@router.post("/api/accounts/sync-all", response_model=SyncAllOut)
def api_sync_all_accounts() -> SyncAllOut:
    """Enqueue a sync for every sync-enabled account (paged; deduped by the job queue)."""
    Session = get_session_factory()
    job_ids: list[str] = []
    with Session() as session:
        offset = 0
        while True:
            rows, total = list_accounts(session, limit=_SYNC_ALL_PAGE, offset=offset)
            for acc in rows:
                if acc.sync_enabled:
                    job_ids.append(str(enqueue_account_sync(session, acc.id)))
            offset += len(rows)
            if not rows or offset >= total:
                break
        session.commit()
    return SyncAllOut(job_ids=job_ids, count=len(job_ids))


@router.get("/api/groups", response_model=GroupsOut)
def api_list_groups() -> GroupsOut:
    Session = get_session_factory()
    with Session() as session:
        return GroupsOut(
            groups=[GroupOut(id=str(g.id), name=g.name, color=g.color, account_count=n) for g, n in list_groups(session)]
        )


@router.post("/api/groups", response_model=GroupOut)
def api_create_group(body: GroupCreateIn) -> GroupOut:
    Session = get_session_factory()
    with Session() as session:
        g = create_group(session, name=body.name, color=body.color)
        session.commit()
        return GroupOut(id=str(g.id), name=g.name, color=g.color, account_count=0)


@router.delete("/api/groups/{group_id}", status_code=204, response_class=Response)
def api_delete_group(group_id: UUID) -> Response:
    Session = get_session_factory()
    with Session() as session:
        try:
            delete_group(session, group_id)
            session.commit()
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
    return Response(status_code=204)


@router.get("/api/settings", response_model=SettingsOut)
def api_get_settings() -> SettingsOut:
    Session = get_session_factory()
    with Session() as session:
        return SettingsOut(settings=get_public_settings(session))


@router.put("/api/settings", response_model=SettingsOut)
def api_update_settings(body: SettingsUpdateIn) -> SettingsOut:
    """Update public settings only. Password changes use POST /api/auth/password."""
    Session = get_session_factory()
    with Session() as session:
        try:
            settings = update_public_settings(session, body.settings)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        session.commit()
        return SettingsOut(settings=settings)
