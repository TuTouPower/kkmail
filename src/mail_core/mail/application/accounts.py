"""Account and group application services and DTOs (architecture layer boundary)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

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


@dataclass(frozen=True, slots=True)
class AccountDTO:
    id: str
    email: str
    provider: str
    display_name: str | None
    group_id: str | None
    group_name: str | None
    group_color: str | None
    status: str
    sync_status: str
    sync_enabled: bool
    account_type: str
    remark: str | None


@dataclass(frozen=True, slots=True)
class AccountPageDTO:
    accounts: list[AccountDTO]
    total: int
    limit: int
    offset: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class GroupDTO:
    id: str
    name: str
    color: str | None
    account_count: int


@dataclass(frozen=True, slots=True)
class SyncJobDTO:
    job_id: str


@dataclass(frozen=True, slots=True)
class SyncAllDTO:
    job_ids: list[str]
    count: int


@dataclass(frozen=True, slots=True)
class SettingsDTO:
    settings: dict[str, str]


def _to_account_dto(acc: Account, groups: dict[UUID, AccountGroup]) -> AccountDTO:
    g = groups.get(acc.group_id) if acc.group_id else None
    remark = None
    if isinstance(acc.config, dict):
        val = acc.config.get("remark")
        if val is not None:
            remark = str(val)
    return AccountDTO(
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


def list_accounts_app(
    *,
    group_id: UUID | None = None,
    limit: int = 200,
    offset: int = 0,
) -> AccountPageDTO:
    Session = get_session_factory()
    with Session() as session:
        rows, total = list_accounts(session, group_id=group_id, limit=limit, offset=offset)
        gmap = {g.id: g for g, _n in list_groups(session)}
        items = [_to_account_dto(a, gmap) for a in rows]
        return AccountPageDTO(
            accounts=items,
            total=total,
            limit=limit,
            offset=offset,
            has_more=offset + len(items) < total,
        )


def create_account_app(
    *,
    email: str,
    provider: str,
    display_name: str | None = None,
    group_id: UUID | None = None,
    config: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
) -> AccountDTO:
    Session = get_session_factory()
    with Session() as session:
        try:
            acc = create_account(
                session,
                email=email,
                provider=provider,
                display_name=display_name,
                group_id=group_id,
                config=config,
                credentials=credentials,
            )
            # AC-002: Automatically enqueue initial sync job for newly created accounts
            if acc.sync_enabled:
                try:
                    enqueue_account_sync(session, acc.id)
                except Exception:
                    pass
            session.commit()
        except Exception:
            session.rollback()
            raise
        gmap = {g.id: g for g, _n in list_groups(session)}
        return _to_account_dto(acc, gmap)


def update_account_app(
    account_id: UUID,
    *,
    display_name: str | None = None,
    group_id: UUID | None = None,
    clear_group: bool = False,
    sync_enabled: bool | None = None,
    config: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
) -> AccountDTO:
    Session = get_session_factory()
    with Session() as session:
        group_arg: object = ...
        if clear_group:
            group_arg = None
        elif group_id is not None:
            group_arg = group_id
        try:
            acc = update_account(
                session,
                account_id,
                display_name=display_name,
                group_id=group_arg,
                sync_enabled=sync_enabled,
                config_patch=config,
                credentials=credentials,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        gmap = {g.id: g for g, _n in list_groups(session)}
        return _to_account_dto(acc, gmap)


def delete_account_app(account_id: UUID) -> None:
    Session = get_session_factory()
    with Session() as session:
        try:
            delete_account(session, account_id)
            session.commit()
        except Exception:
            session.rollback()
            raise


def sync_account_app(account_id: UUID) -> SyncJobDTO:
    Session = get_session_factory()
    with Session() as session:
        try:
            job_id = enqueue_account_sync(session, account_id)
            session.commit()
            return SyncJobDTO(job_id=str(job_id))
        except Exception:
            session.rollback()
            raise


def sync_all_accounts_app(page_size: int = 500) -> SyncAllDTO:
    Session = get_session_factory()
    job_ids: list[str] = []
    with Session() as session:
        try:
            offset = 0
            while True:
                rows, total = list_accounts(session, limit=page_size, offset=offset)
                for acc in rows:
                    if acc.sync_enabled:
                        job_ids.append(str(enqueue_account_sync(session, acc.id)))
                offset += len(rows)
                if not rows or offset >= total:
                    break
            session.commit()
            return SyncAllDTO(job_ids=job_ids, count=len(job_ids))
        except Exception:
            session.rollback()
            raise


def list_groups_app() -> list[GroupDTO]:
    Session = get_session_factory()
    with Session() as session:
        return [
            GroupDTO(id=str(g.id), name=g.name, color=g.color, account_count=n)
            for g, n in list_groups(session)
        ]


def create_group_app(*, name: str, color: str | None = None) -> GroupDTO:
    Session = get_session_factory()
    with Session() as session:
        try:
            g = create_group(session, name=name, color=color)
            session.commit()
            return GroupDTO(id=str(g.id), name=g.name, color=g.color, account_count=0)
        except Exception:
            session.rollback()
            raise


def delete_group_app(group_id: UUID) -> None:
    Session = get_session_factory()
    with Session() as session:
        try:
            delete_group(session, group_id)
            session.commit()
        except Exception:
            session.rollback()
            raise


def get_settings_app() -> SettingsDTO:
    Session = get_session_factory()
    with Session() as session:
        return SettingsDTO(settings=get_public_settings(session))


def update_settings_app(settings: dict[str, str]) -> SettingsDTO:
    Session = get_session_factory()
    with Session() as session:
        try:
            updated = update_public_settings(session, settings)
            session.commit()
            return SettingsDTO(settings=updated)
        except Exception:
            session.rollback()
            raise
