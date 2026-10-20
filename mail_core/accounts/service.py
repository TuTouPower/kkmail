"""Account registry — stores credential_ref only (no raw secrets)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from mail_core.accounts.credentials import get_credential_store, save_json_secret
from mail_core.mail.domain.enums import JobType, ProviderType
from mail_core.mail.storage.models import Account, AccountGroup
from mail_core.sync.jobs import enqueue_job


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
    email_norm = email.strip().lower()
    ref = credential_ref
    if credentials is not None:
        ref = ref or f"account:{email_norm}"
        save_json_secret(get_credential_store(), ref, credentials)
    acc = Account(
        email=email_norm,
        provider=str(provider),
        credential_ref=ref,
        display_name=display_name,
        config=config or {},
        group_id=group_id,
    )
    session.add(acc)
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
    stmt = select(Account).order_by(Account.email.asc()).offset(max(0, offset)).limit(min(500, max(1, limit)))
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
) -> Account:
    acc = session.get(Account, account_id)
    if acc is None:
        raise LookupError("account not found")
    if display_name is not None:
        acc.display_name = display_name
    if group_id is not ...:
        acc.group_id = group_id  # type: ignore[assignment]
    if sync_enabled is not None:
        acc.sync_enabled = sync_enabled
    if config_patch:
        merged = dict(acc.config or {})
        merged.update(config_patch)
        acc.config = merged
    if credentials is not None:
        ref = acc.credential_ref or f"account:{acc.email}"
        acc.credential_ref = ref
        save_json_secret(get_credential_store(), ref, credentials)
    session.flush()
    return acc


def delete_account(session: Session, account_id: uuid.UUID) -> None:
    acc = session.get(Account, account_id)
    if acc is None:
        raise LookupError("account not found")
    session.delete(acc)
    session.flush()


def enqueue_account_sync(session: Session, account_id: uuid.UUID) -> uuid.UUID:
    acc = session.get(Account, account_id)
    if acc is None:
        raise LookupError("account not found")
    job = enqueue_job(
        session,
        job_type=JobType.SYNC_ACCOUNT_FOLDERS.value,
        account_id=account_id,
        payload={},
        priority=50,
        dedupe_key=f"sync-folders:{account_id}",
    )
    acc.sync_status = "running"
    session.flush()
    return job.id


def create_group(session: Session, *, name: str, color: str | None = None) -> AccountGroup:
    g = AccountGroup(name=name.strip(), color=color)
    session.add(g)
    session.flush()
    return g


def list_groups(session: Session) -> list[tuple[AccountGroup, int]]:
    rows = session.execute(
        select(AccountGroup, func.count(Account.id))
        .outerjoin(Account, Account.group_id == AccountGroup.id)
        .group_by(AccountGroup.id)
        .order_by(AccountGroup.sort_order.asc(), AccountGroup.name.asc())
    ).all()
    return [(g, int(n or 0)) for g, n in rows]


def delete_group(session: Session, group_id: uuid.UUID) -> None:
    g = session.get(AccountGroup, group_id)
    if g is None:
        raise LookupError("group not found")
    session.delete(g)
    session.flush()
