"""Account registry — stores credential_ref only (no raw secrets)."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import cast
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from mail_core.accounts.credentials import get_credential_store, save_json_secret
from mail_core.mail.domain.enums import JobType, ProviderType, SyncStatus
from mail_core.mail.storage.models import Account, AccountGroup
from mail_core.sync.jobs import enqueue_job

SIDEBAR_LAYOUT_LOCK_ID = 0x4B4B4D41494C  # Stable advisory lock key for organization writes.


class StaleSidebarLayoutError(RuntimeError):
    """Raised when a full-layout write was based on an older snapshot."""


def create_account(
    session: Session,
    *,
    email: str,
    provider: ProviderType | str,
    credential_ref: str | None = None,
    display_name: str | None = None,
    config: dict | None = None,
    group_id: uuid.UUID | None = None,
    credentials: dict | None = None,
) -> Account:
    lock_sidebar_layout(session)
    email_norm = email.strip().lower()
    from mail_core.accounts.connection import validate_connection

    validate_connection(
        email_norm,
        str(provider).lower(),
        config or {},
        credentials,
        require_credentials=credentials is not None,
    )
    acc = Account(
        email=email_norm,
        provider=str(provider),
        credential_ref=credential_ref,
        display_name=display_name,
        config=config or {},
        group_id=group_id,
    )
    master_max = session.scalar(select(func.max(Account.master_order)))
    if master_max is not None:
        acc.master_order = master_max + 1
    if group_id is not None:
        group_max = session.scalar(select(func.max(Account.group_order)).where(Account.group_id == group_id))
        if group_max is not None:
            acc.group_order = group_max + 1
    session.add(acc)
    session.flush()

    if credentials is not None:
        ref = credential_ref or f"account:{acc.id}"
        save_json_secret(get_credential_store(), ref, credentials, session=session)
        acc.credential_ref = ref
        session.flush()

    return acc


def get_account(session: Session, account_id: uuid.UUID) -> Account | None:
    return session.get(Account, account_id)


def list_accounts(
    session: Session,
    *,
    group_id: uuid.UUID | None = None,
    limit: int = 200,
    offset: int = 0,
) -> tuple[list[Account], int]:
    total = session.scalar(select(func.count()).select_from(Account)) or 0
    order_column = Account.group_order if group_id is not None else Account.master_order
    manual_order_exists = session.scalar(select(func.count()).select_from(Account).where(order_column.is_not(None)))
    if group_id is not None:
        manual_order_exists = session.scalar(
            select(func.count()).select_from(Account).where(Account.group_id == group_id, Account.group_order.is_not(None))
        )
    if manual_order_exists:
        ordering = [order_column.asc(), func.split_part(func.lower(Account.email), "@", 2), func.lower(Account.email), Account.email]
    else:
        ordering = [func.split_part(func.lower(Account.email), "@", 2), func.lower(Account.email), Account.email]
    stmt = select(Account).order_by(*ordering).offset(max(0, offset)).limit(min(500, max(1, limit)))
    if group_id is not None:
        stmt = stmt.where(Account.group_id == group_id)
        total = session.scalar(select(func.count()).select_from(Account).where(Account.group_id == group_id)) or 0
    return list(session.scalars(stmt).all()), int(total)


def update_account(
    session: Session,
    account_id: uuid.UUID,
    *,
    display_name: str | None = None,
    group_id: uuid.UUID | None | object = ...,
    sync_enabled: bool | None = None,
    config_patch: dict | None = None,
    credentials: dict | None = None,
    clear_credentials: list[str] | None = None,
) -> Account:
    # R16: take the sidebar (organization) advisory lock before the
    # Account row lock for every update, not only group changes, so no
    # caller of this service can invert the unified order
    # sidebar -> Account -> OAuth flow/credentials. Re-acquisition by a
    # caller that already holds the lock in this transaction is a no-op
    # wait (the session already owns it).
    lock_sidebar_layout(session)
    acc = session.scalar(select(Account).where(Account.id == account_id).with_for_update())
    if acc is None:
        raise LookupError("account not found")
    from mail_core.accounts.connection import validate_connection, merge_credentials, reject_microsoft_imap
    from mail_core.accounts.credentials import credential_edit
    effective_config = {**(acc.config or {}), **(config_patch or {})}
    if acc.provider == "imap" and (config_patch or credentials or clear_credentials or sync_enabled is True):
        reject_microsoft_imap(acc.email, effective_config)
    if config_patch:
        validate_connection(acc.email, acc.provider, effective_config, None, require_credentials=False)
    auth_config_changed = any(key in (config_patch or {}) and effective_config.get(key) != (acc.config or {}).get(key) for key in ("oauth_client_type",))
    if credentials or clear_credentials or auth_config_changed:
        ref = acc.credential_ref or f"account:{acc.id}"
        with credential_edit(get_credential_store(), ref, session=session) as saved:
            merged_credentials = merge_credentials(
                acc.provider,
                saved,
                credentials or {},
                clear_fields=set(clear_credentials or ()),
            )
            validate_connection(acc.email, acc.provider, effective_config, merged_credentials)
            if auth_config_changed:
                merged_credentials.pop("access_token", None)
                merged_credentials.pop("expires_at", None)
            saved.clear()
            saved.update(merged_credentials)
        acc.credential_ref = ref
    if display_name is not None:
        acc.display_name = display_name
    if group_id is not ...:
        _update_account_group(session, acc, cast(uuid.UUID | None, group_id))
    if sync_enabled is not None:
        acc.sync_enabled = sync_enabled
        if not sync_enabled:
            acc.sync_status = SyncStatus.IDLE.value
    if config_patch:
        merged = dict(acc.config or {})
        merged.update(config_patch)
        for key in ("imap_user", "username"):
            if key in config_patch and (config_patch[key] is None or not str(config_patch[key]).strip()):
                merged.pop(key, None)
        if (acc.provider or "").lower() == "imap":
            imap_host = merged.get("imap_host") or merged.get("host")
            if imap_host:
                from mail_core.providers.factory import validate_imap_host

                validate_imap_host(imap_host)
        acc.config = merged
    session.flush()
    return acc


def _update_account_group(session: Session, account: Account, group_id: uuid.UUID | None) -> None:
    if group_id is not None:
        group = session.scalar(select(AccountGroup).where(AccountGroup.id == group_id).with_for_update())
        if group is None:
            raise LookupError("group not found")
        if group_id != account.group_id:
            group_max = session.scalar(select(func.max(Account.group_order)).where(Account.group_id == group_id))
            account.group_order = group_max + 1 if group_max is not None else None
    elif group_id is None:
        account.group_order = None
    account.group_id = group_id  # type: ignore[assignment]


def delete_account(session: Session, account_id: uuid.UUID) -> None:
    lock_sidebar_layout(session)
    acc = session.get(Account, account_id)
    if acc is None:
        raise LookupError("account not found")
    ref = acc.credential_ref
    session.delete(acc)
    session.flush()
    if ref and not ref.startswith("env:"):
        # App-owned secret: remove it with the account (env refs are operator-managed).
        store = get_credential_store()
        try:
            store.delete_secret(ref, session=session)
        except TypeError:
            store.delete_secret(ref)


def enqueue_account_sync(session: Session, account_id: uuid.UUID) -> uuid.UUID:
    acc = session.get(Account, account_id)
    if acc is None:
        raise LookupError("account not found")
    if not acc.sync_enabled:
        raise ValueError("account sync is disabled")
    job = enqueue_job(
        session,
        job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
        account_id=account_id,
        payload={},
        priority=50,
        dedupe_key=f"sync-folders:{account_id}",
    )
    acc.sync_status = SyncStatus.RUNNING.value
    session.flush()
    return job.id


def create_group(session: Session, *, name: str, color: str | None = None) -> AccountGroup:
    lock_sidebar_layout(session)
    normalized = name.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("group name must contain 1 to 128 characters")
    last_order = session.scalar(select(func.max(AccountGroup.sort_order)))
    g = AccountGroup(name=normalized, color=color, sort_order=(last_order + 1 if last_order is not None else 0))
    session.add(g)
    try:
        session.flush()
    except IntegrityError as exc:
        raise ValueError("group name already exists") from exc
    return g


def rename_group(session: Session, group_id: uuid.UUID, *, name: str) -> AccountGroup:
    lock_sidebar_layout(session)
    group = session.get(AccountGroup, group_id)
    if group is None:
        raise LookupError("group not found")
    normalized = name.strip()
    if not normalized or len(normalized) > 128:
        raise ValueError("group name must contain 1 to 128 characters")
    group.name = normalized
    try:
        session.flush()
    except IntegrityError as exc:
        raise ValueError("group name already exists") from exc
    return group


def save_sidebar_layout(
    session: Session,
    *,
    expected_revision: str,
    group_ids: list[uuid.UUID],
    master_account_ids: list[uuid.UUID],
    ungrouped_account_ids: list[uuid.UUID],
    group_account_ids: dict[uuid.UUID, list[uuid.UUID]],
) -> None:
    lock_sidebar_layout(session)
    groups = list(session.scalars(select(AccountGroup).order_by(AccountGroup.id).with_for_update()).all())
    accounts = list(session.scalars(select(Account).order_by(Account.id).with_for_update()).all())
    if _sidebar_layout_revision(groups, accounts) != expected_revision:
        raise StaleSidebarLayoutError("sidebar layout changed; reload and retry")
    _validate_sidebar_layout(group_ids, master_account_ids, ungrouped_account_ids, group_account_ids, groups, accounts)
    _apply_sidebar_layout(session, group_ids, master_account_ids, ungrouped_account_ids, group_account_ids, groups, accounts)


def get_sidebar_layout(session: Session) -> dict[str, object]:
    rows = session.execute(
        select(AccountGroup, Account)
        .select_from(AccountGroup)
        .outerjoin(Account, Account.group_id == AccountGroup.id, full=True)
    ).all()
    groups_by_id = {group.id: group for group, _account in rows if group is not None}
    accounts_by_id = {account.id: account for _group, account in rows if account is not None}
    groups = sorted(groups_by_id.values(), key=lambda group: (group.sort_order, group.name, group.id))
    accounts = list(accounts_by_id.values())
    group_ids = [group.id for group in groups]
    ordered_master = _ordered_accounts(accounts, "master_order")
    members_by_group_id: dict[uuid.UUID, list[Account]] = {}
    for account in accounts:
        if account.group_id is not None:
            members_by_group_id.setdefault(account.group_id, []).append(account)
    group_account_ids = {
        group.id: [account.id for account in _ordered_accounts(members_by_group_id.get(group.id, []), "group_order")]
        for group in groups
    }
    return {
        "revision": _sidebar_layout_revision(groups, accounts),
        "group_ids": group_ids,
        "master_account_ids": [account.id for account in ordered_master],
        "ungrouped_account_ids": [account.id for account in ordered_master if account.group_id is None],
        "group_account_ids": group_account_ids,
    }


def _ordered_accounts(accounts: list[Account], order_field: str) -> list[Account]:
    def email_key(account: Account) -> tuple[str, str, str]:
        email = account.email or ""
        lowered = email.lower()
        return lowered.rsplit("@", 1)[-1], lowered, email

    if any(getattr(account, order_field) is not None for account in accounts):
        return sorted(accounts, key=lambda account: (
            getattr(account, order_field) is None,
            getattr(account, order_field) if getattr(account, order_field) is not None else 0,
            *email_key(account),
        ))
    return sorted(accounts, key=email_key)


def _sidebar_layout_revision(groups: list[AccountGroup], accounts: list[Account]) -> str:
    state = {
        "groups": sorted((str(group.id), group.name, group.sort_order) for group in groups),
        "accounts": sorted(
            (str(account.id), account.email, str(account.group_id) if account.group_id else None,
             account.master_order, account.group_order)
            for account in accounts
        ),
    }
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_sidebar_layout(
    group_ids: list[uuid.UUID],
    master_account_ids: list[uuid.UUID],
    ungrouped_account_ids: list[uuid.UUID],
    group_account_ids: dict[uuid.UUID, list[uuid.UUID]],
    groups: list[AccountGroup],
    accounts: list[Account],
) -> None:
    known_group_ids = {group.id for group in groups}
    known_account_ids = {account.id for account in accounts}
    if len(group_ids) != len(set(group_ids)) or set(group_ids) != known_group_ids:
        raise ValueError("group order must include every group exactly once")
    if len(master_account_ids) != len(set(master_account_ids)) or set(master_account_ids) != known_account_ids:
        raise ValueError("account order must include every account exactly once")
    if len(ungrouped_account_ids) != len(set(ungrouped_account_ids)):
        raise ValueError("ungrouped account list contains duplicates")
    if set(group_account_ids) != known_group_ids:
        raise ValueError("group membership payload must include every group")
    grouped_ids: list[uuid.UUID] = []
    for group_id, member_ids in group_account_ids.items():
        if len(member_ids) != len(set(member_ids)):
            raise ValueError("group account list contains duplicates")
        grouped_ids.extend(member_ids)
    if len(grouped_ids) != len(set(grouped_ids)):
        raise ValueError("an account cannot belong to multiple groups")
    if set(grouped_ids).intersection(ungrouped_account_ids):
        raise ValueError("an account cannot be grouped and ungrouped")
    if set(grouped_ids).union(ungrouped_account_ids) != known_account_ids:
        raise ValueError("group membership payload must include every account")


def _apply_sidebar_layout(
    session: Session,
    group_ids: list[uuid.UUID],
    master_account_ids: list[uuid.UUID],
    ungrouped_account_ids: list[uuid.UUID],
    group_account_ids: dict[uuid.UUID, list[uuid.UUID]],
    groups: list[AccountGroup],
    accounts: list[Account],
) -> None:
    group_by_id = {group.id: group for group in groups}
    account_by_id = {account.id: account for account in accounts}
    for index, group_id in enumerate(group_ids):
        group_by_id[group_id].sort_order = index
    for index, account_id in enumerate(master_account_ids):
        account_by_id[account_id].master_order = index
    for account_id in ungrouped_account_ids:
        account_by_id[account_id].group_id = None
        account_by_id[account_id].group_order = None
    for group_id, member_ids in group_account_ids.items():
        for index, account_id in enumerate(member_ids):
            account = account_by_id[account_id]
            account.group_id = group_id
            account.group_order = index
    session.flush()


def reset_sidebar_account_order(session: Session, *, expected_revision: str) -> None:
    lock_sidebar_layout(session)
    groups = list(session.scalars(select(AccountGroup).order_by(AccountGroup.id).with_for_update()).all())
    accounts = list(session.scalars(select(Account).order_by(Account.id).with_for_update()).all())
    if _sidebar_layout_revision(groups, accounts) != expected_revision:
        raise StaleSidebarLayoutError("sidebar layout changed; reload and retry")
    for account in accounts:
        account.master_order = None
        account.group_order = None
    session.flush()


def list_groups(session: Session) -> list[tuple[AccountGroup, int]]:
    rows = session.execute(
        select(AccountGroup, func.count(Account.id))
        .outerjoin(Account, Account.group_id == AccountGroup.id)
        .group_by(AccountGroup.id)
        .order_by(AccountGroup.sort_order.asc(), AccountGroup.name.asc())
    ).all()
    return [(g, int(n or 0)) for g, n in rows]


def account_ids_for_group(session: Session, group_id: uuid.UUID) -> list[uuid.UUID]:
    if session.get(AccountGroup, group_id) is None:
        raise LookupError("group not found")
    return list(session.scalars(select(Account.id).where(Account.group_id == group_id).order_by(Account.id)).all())


def enabled_account_ids(session: Session, group_id: uuid.UUID | None = None) -> list[uuid.UUID]:
    """Return enabled accounts for an aggregate scope, validating a requested group."""
    stmt = select(Account.id).where(Account.sync_enabled.is_(True))
    if group_id is not None:
        if session.get(AccountGroup, group_id) is None:
            raise LookupError("group not found")
        stmt = stmt.where(Account.group_id == group_id)
    return list(session.scalars(stmt.order_by(Account.id)).all())


def delete_group(session: Session, group_id: uuid.UUID) -> None:
    lock_sidebar_layout(session)
    g = session.scalar(select(AccountGroup).where(AccountGroup.id == group_id).with_for_update())
    if g is None:
        raise LookupError("group not found")
    for account in session.scalars(select(Account).where(Account.group_id == group_id).with_for_update()):
        account.group_id = None
        account.group_order = None
    session.delete(g)
    session.flush()


def lock_sidebar_layout(session: Session) -> None:
    session.execute(select(func.pg_advisory_xact_lock(SIDEBAR_LAYOUT_LOCK_ID)))


def update_account_sync_status(
    session: Session,
    account_id: uuid.UUID,
    status: SyncStatus,
    *,
    error: str | None = None,
    synced_at: datetime | None = None,
) -> Account | None:
    acc = session.get(Account, account_id)
    if acc is None:
        return None
    acc.sync_status = status.value
    ts = synced_at or datetime.now(timezone.utc)
    cfg = dict(acc.config or {})
    cfg["last_synced_at"] = ts.isoformat()
    if error:
        from mail_core.security.redact import safe_provider_summary

        cfg["last_sync_error"] = safe_provider_summary(error)
    elif status == SyncStatus.IDLE:
        cfg.pop("last_sync_error", None)
    acc.config = cfg
    if hasattr(acc, "last_synced_at"):
        setattr(acc, "last_synced_at", ts)
    session.flush()
    return acc
