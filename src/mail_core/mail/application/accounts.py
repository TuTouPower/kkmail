"""Account and group application services and DTOs (architecture layer boundary)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from mail_core.accounts import (
    create_account,
    create_group,
    delete_account,
    delete_group,
    enqueue_account_sync,
    get_sidebar_layout,
    get_public_settings,
    list_accounts,
    list_groups,
    rename_group,
    reset_sidebar_account_order,
    save_sidebar_layout,
    update_account,
    update_public_settings,
)
from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import OutboxEventType
from mail_core.mail.storage.models import Account, AccountGroup, OutboxEvent
from mail_core.security.redact import safe_error

log = logging.getLogger("mail_core.mail.application.accounts")
SYNC_ALL_JOB_ID_SAMPLE_LIMIT = 100


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
    master_order: int | None = None
    group_order: int | None = None
    imap_config: dict[str, Any] | None = None
    provider_profile: str | None = None
    oauth_client_type: str | None = None
    oauth_tenant: str | None = None
    recipient_addresses: list[str] = field(default_factory=list)


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
    sort_order: int


@dataclass(frozen=True, slots=True)
class SyncJobDTO:
    job_id: str


@dataclass(frozen=True, slots=True)
class SyncAllDTO:
    job_ids: list[str]
    count: int


@contextmanager
def _run_in_session() -> Iterator[Any]:
    """Single transaction boundary for mutating ``*_app`` functions (A247).

    Yields a session; commits exactly once when the body completes and
    rolls back then re-raises on any error (including a failed commit).
    Read-only ``*_app`` functions keep using a plain session instead.
    """
    Session = get_session_factory()
    with Session() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def _enqueue_initial_sync(session: Any, account_id: UUID) -> None:
    try:
        enqueue_account_sync(session, account_id)
    except Exception as exc:
        log.warning("initial sync enqueue failed for account %s: %s", account_id, safe_error(exc))


@dataclass(frozen=True, slots=True)
class SettingsDTO:
    settings: dict[str, str]


def _groups_by_id(session: Any) -> dict[UUID, AccountGroup]:
    return {group.id: group for group in session.scalars(select(AccountGroup)).all()}


def _to_account_dto(acc: Account, groups: dict[UUID, AccountGroup]) -> AccountDTO:
    g = groups.get(acc.group_id) if acc.group_id else None
    remark = None
    imap_config = None
    if isinstance(acc.config, dict):
        val = acc.config.get("remark")
        if val is not None:
            remark = str(val)
        if (acc.provider or "").lower() == "imap":
            use_ssl_value = acc.config.get("use_ssl", True)
            use_ssl = (
                use_ssl_value
                if isinstance(use_ssl_value, bool)
                else str(use_ssl_value).strip().lower() not in ("0", "false", "no", "off")
            )
            port_value = acc.config.get("imap_port") or acc.config.get("port")
            try:
                port = int(port_value) if port_value is not None else (993 if use_ssl else 143)
            except (TypeError, ValueError):
                port = 993 if use_ssl else 143
            raw_user = acc.config.get("imap_user") or acc.config.get("username")
            imap_user = raw_user.strip() if isinstance(raw_user, str) and raw_user.strip() else None
            imap_config = {
                **({"imap_user": imap_user} if imap_user else {}),
                "imap_host": acc.config.get("imap_host") or acc.config.get("host"),
                "imap_port": port,
                "use_ssl": use_ssl,
            }
    return AccountDTO(
        id=str(acc.id),
        email=acc.email,
        provider=acc.provider,
        display_name=acc.display_name,
        group_id=str(acc.group_id) if acc.group_id else None,
        group_name=g.name if g else None,
        group_color=g.color if g else None,
        master_order=acc.master_order,
        group_order=acc.group_order,
        # A234: status is derived from the account's real state, not a
        # hard-coded constant — sync-disabled accounts report "disabled";
        # the detailed sync state stays in sync_status.
        status="active" if acc.sync_enabled else "disabled",
        sync_status=acc.sync_status,
        sync_enabled=acc.sync_enabled,
        account_type=acc.provider,
        remark=remark,
        imap_config=imap_config,
        provider_profile=(acc.config or {}).get("provider_profile"),
        oauth_client_type=(acc.config or {}).get("oauth_client_type"),
        oauth_tenant=(acc.config or {}).get("oauth_tenant"),
        recipient_addresses=list(getattr(acc, "recipient_addresses", None) or []),
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
        gmap = _groups_by_id(session)
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
    oauth_flow_id: str | None = None,
    principal: Any = None,
) -> AccountDTO:
    if oauth_flow_id and credentials:
        raise ValueError("不能同时提交 OAuth 授权结果和手动凭据，请选择一种保存方式")
    with _run_in_session() as session:
        if oauth_flow_id:
            from mail_core.accounts.oauth_flow import consume_oauth_flow_for_create
            from mail_core.accounts.service import lock_sidebar_layout

            # All OAuth saves lock organization before flow/pointer/credentials.
            lock_sidebar_layout(session)
            email, config, credentials = consume_oauth_flow_for_create(
                session,
                flow_id=oauth_flow_id,
                principal=principal,
                provider=provider,
                config=config,
                group_id=group_id,
            )
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
            _enqueue_initial_sync(session, acc.id)
        gmap = _groups_by_id(session)
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
    clear_credentials: list[str] | None = None,
    oauth_flow_id: str | None = None,
    principal: Any = None,
) -> AccountDTO:
    if oauth_flow_id and (credentials or clear_credentials):
        raise ValueError("不能同时提交 OAuth 授权结果和手动凭据修改，请选择一种保存方式")
    with _run_in_session() as session:
        group_arg: object = ...
        if clear_group:
            group_arg = None
        elif group_id is not None:
            group_arg = group_id
        # R16: unified lock order for every account update is
        # sidebar (organization) advisory lock -> Account row ->
        # OAuth flow/credentials. The sidebar lock must be taken
        # before ANY Account row lock in this entry path — including
        # the prior_sync_enabled snapshot below and plain
        # sync-preference-only updates — otherwise a combined PATCH
        # (account lock held, then waiting for the sidebar lock)
        # deadlocks against layout/organization transactions that
        # take sidebar -> Account (SQLSTATE 40P01).
        from mail_core.accounts.service import lock_sidebar_layout

        lock_sidebar_layout(session)
        prior_sync_enabled = None
        if sync_enabled is not None:
            account_row = session.scalar(select(Account).where(Account.id == account_id).with_for_update())
            if account_row is None:
                raise LookupError("account not found")
            prior_sync_enabled = account_row.sync_enabled
        if oauth_flow_id:
            from mail_core.accounts.oauth_flow import consume_oauth_flow_for_reauthorize

            # Sidebar lock already held (see above); next lock the
            # Account row, then consume the OAuth flow/credentials.
            acc_row = session.scalar(select(Account).where(Account.id == account_id).with_for_update())
            if acc_row is None:
                raise LookupError("account not found")
            consume_oauth_flow_for_reauthorize(
                session,
                account=acc_row,
                flow_id=oauth_flow_id,
                principal=principal,
                config_patch=config,
                group_id=group_arg,
            )
            config = None
        acc = update_account(
            session,
            account_id,
            display_name=display_name,
            group_id=group_arg,
            sync_enabled=sync_enabled,
            config_patch=config,
            credentials=credentials,
            clear_credentials=clear_credentials,
        )
        if prior_sync_enabled is not None and prior_sync_enabled != acc.sync_enabled:
            session.add(OutboxEvent(
                event_type=OutboxEventType.ACCOUNT_UPDATED.value,
                account_id=acc.id,
                payload={"sync_enabled": acc.sync_enabled},
            ))
        if oauth_flow_id and acc.sync_enabled:
            _enqueue_initial_sync(session, acc.id)
        gmap = _groups_by_id(session)
        return _to_account_dto(acc, gmap)


def delete_account_app(account_id: UUID) -> None:
    with _run_in_session() as session:
        delete_account(session, account_id)


def sync_account_app(account_id: UUID) -> SyncJobDTO:
    with _run_in_session() as session:
        job_id = enqueue_account_sync(session, account_id)
        return SyncJobDTO(job_id=str(job_id))


def sync_all_accounts_app(page_size: int = 500) -> SyncAllDTO:
    """Enqueue a sync job for every sync-enabled account, all-or-nothing.

    A114: previously this paged with OFFSET and committed after every page,
    so a mid-run failure left a prefix of accounts enqueued and concurrent
    inserts/deletes shifted later pages. Now phase 1 collects every
    sync-enabled account id with keyset pagination (``id`` cursor, immune
    to offset drift) and phase 2 enqueues them all inside the same single
    transaction — one commit on success, full rollback on any failure, so
    callers never observe a partially enqueued sync-all.
    """
    page_size = max(1, page_size)
    job_ids: list[str] = []
    with _run_in_session() as session:
        account_ids: list[UUID] = []
        cursor: UUID | None = None
        while True:
            stmt = (
                select(Account.id)
                .where(Account.sync_enabled.is_(True))
                .order_by(Account.id)
                .limit(page_size)
            )
            if cursor is not None:
                stmt = stmt.where(Account.id > cursor)
            page = list(session.scalars(stmt).all())
            if not page:
                break
            account_ids.extend(page)
            cursor = page[-1]
            if len(page) < page_size:
                break
        for account_id in account_ids:
            job_id = enqueue_account_sync(session, account_id)
            if len(job_ids) < SYNC_ALL_JOB_ID_SAMPLE_LIMIT:
                job_ids.append(str(job_id))
        log.info("sync-all enqueued %d jobs", len(account_ids))
        return SyncAllDTO(job_ids=job_ids, count=len(account_ids))


def list_groups_app() -> list[GroupDTO]:
    Session = get_session_factory()
    with Session() as session:
        return [
            GroupDTO(id=str(g.id), name=g.name, color=g.color, account_count=n, sort_order=g.sort_order)
            for g, n in list_groups(session)
        ]


def create_group_app(*, name: str, color: str | None = None) -> GroupDTO:
    with _run_in_session() as session:
        g = create_group(session, name=name, color=color)
        return GroupDTO(id=str(g.id), name=g.name, color=g.color, account_count=0, sort_order=g.sort_order)


def delete_group_app(group_id: UUID) -> None:
    with _run_in_session() as session:
        delete_group(session, group_id)


def rename_group_app(group_id: UUID, *, name: str) -> GroupDTO:
    with _run_in_session() as session:
        group = rename_group(session, group_id, name=name)
        count = int(
            session.scalar(
                select(func.count()).select_from(Account).where(Account.group_id == group_id)
            )
            or 0
        )
        return GroupDTO(id=str(group.id), name=group.name, color=group.color, account_count=count, sort_order=group.sort_order)


def save_sidebar_layout_app(
    *,
    expected_revision: str,
    group_ids: list[UUID],
    master_account_ids: list[UUID],
    ungrouped_account_ids: list[UUID],
    group_account_ids: dict[UUID, list[UUID]],
) -> None:
    with _run_in_session() as session:
        save_sidebar_layout(
            session,
            expected_revision=expected_revision,
            group_ids=group_ids,
            master_account_ids=master_account_ids,
            ungrouped_account_ids=ungrouped_account_ids,
            group_account_ids=group_account_ids,
        )


def get_sidebar_layout_app() -> dict[str, object]:
    Session = get_session_factory()
    with Session() as session:
        return get_sidebar_layout(session)


def reset_sidebar_account_order_app(*, expected_revision: str) -> None:
    with _run_in_session() as session:
        reset_sidebar_account_order(session, expected_revision=expected_revision)


def get_settings_app() -> SettingsDTO:
    Session = get_session_factory()
    with Session() as session:
        return SettingsDTO(settings=get_public_settings(session))


def update_settings_app(settings: dict[str, str]) -> SettingsDTO:
    with _run_in_session() as session:
        updated = update_public_settings(session, settings)
        return SettingsDTO(settings=updated)
