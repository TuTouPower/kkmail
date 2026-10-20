"""Account registry — stores credential_ref only (no raw secrets)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from mail_core.mail.domain.enums import ProviderType
from mail_core.mail.storage.models import Account


def create_account(
    session: Session,
    *,
    email: str,
    provider: ProviderType | str,
    credential_ref: str | None = None,
    display_name: str | None = None,
    config: dict | None = None,
) -> Account:
    acc = Account(
        email=email,
        provider=str(provider),
        credential_ref=credential_ref,
        display_name=display_name,
        config=config or {},
    )
    session.add(acc)
    session.flush()
    return acc


def get_account(session: Session, account_id: uuid.UUID) -> Account | None:
    return session.get(Account, account_id)


def list_accounts(session: Session) -> list[Account]:
    return list(session.scalars(select(Account).order_by(Account.email)).all())
