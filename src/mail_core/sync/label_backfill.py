"""One-shot backfill of historical Gmail ``\\Important`` label membership.

Regular incremental sync fetches flags only, so messages ingested before
label-aware metadata FETCH never acquired their view location. This module
replays metadata pages through the same provider/parser/upsert path as normal
sync, but writes no checkpoints and never creates duplicate messages.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from mail_core.mail.domain.folder_views import (
    CONTAINER,
    EXCLUDED_FROM_ALL_VIEW_ROLES,
    IMPORTANT_VIEW_REMOTE_IDS,
    VIEW,
    is_gmail_account,
)
from mail_core.mail.storage.models import Account, Folder
from mail_core.providers.connection_slots import TrafficClass
from mail_core.providers.factory import build_provider
from mail_core.security.credentials import CredentialStore, get_credential_store
from mail_core.sync.leases import LeaseBusy, acquire_lease, heartbeat_lease, release_lease
from mail_core.sync.metadata import upsert_messages

LOG = logging.getLogger("mail_core.label_backfill")

LEASE_TTL = timedelta(seconds=120)
OWNER_PREFIX = "label-backfill"


@dataclass(frozen=True, slots=True)
class BackfillResult:
    account_id: uuid.UUID
    status: str
    folders: int = 0
    upserted: int = 0
    detail: str = ""


def _important_view_id(session: Session, account_id: uuid.UUID) -> uuid.UUID | None:
    return session.scalar(
        select(Folder.id).where(
            Folder.account_id == account_id,
            Folder.kind == VIEW,
            or_(Folder.role == "important", Folder.remote_id.in_(IMPORTANT_VIEW_REMOTE_IDS)),
        )
    )


def backfill_account(
    session_factory: Any,
    account_id: uuid.UUID,
    *,
    force: bool = False,
    store: CredentialStore | None = None,
    traffic_class: TrafficClass = TrafficClass.BACKGROUND,
    provider_factory: Any = build_provider,
) -> BackfillResult:
    owner_id = f"{OWNER_PREFIX}-{uuid.uuid4().hex}"
    with session_factory() as session:
        account = session.get(Account, account_id)
        if account is None:
            return BackfillResult(account_id, "account_not_found")
        if not is_gmail_account(account):
            return BackfillResult(account_id, "skipped_not_gmail")
        if account.label_backfill_completed_at is not None and not force:
            return BackfillResult(account_id, "skipped_completed")
        view_id = _important_view_id(session, account_id)
        if view_id is None:
            return BackfillResult(account_id, "skipped_no_view")
        folders = list(
            session.execute(
                select(Folder.id, Folder.remote_id).where(
                    Folder.account_id == account_id,
                    Folder.kind == CONTAINER,
                    Folder.role.notin_(EXCLUDED_FROM_ALL_VIEW_ROLES),
                    Folder.sync_status != "paused",
                )
            ).all()
        )
        try:
            lease = acquire_lease(
                session, account_id=account_id, owner_id=owner_id, ttl=LEASE_TTL
            )
            # Build the provider while ``account`` is still attached: the
            # adapter reads credential/config fields at construction time.
            provider = provider_factory(
                account, store or get_credential_store(), traffic_class=traffic_class
            )
            session.commit()
        except LeaseBusy:
            session.rollback()
            return BackfillResult(account_id, "lease_busy")
        except Exception as exc:
            session.rollback()
            return BackfillResult(account_id, "failed", detail=str(exc))

    upserted = 0
    try:
        for folder_id, remote_id in folders:
            cursor = None
            while True:
                page = provider.fetch_metadata_page(str(remote_id), cursor)  # network
                with session_factory() as session:
                    heartbeat_lease(
                        session,
                        account_id=account_id,
                        owner_id=owner_id,
                        fencing_token=lease.fencing_token,
                        ttl=LEASE_TTL,
                    )
                    upsert_messages(
                        session,
                        account_id=account_id,
                        folder_id=folder_id,
                        metas=list(page.items),
                        label_view_folders={"\\Important": view_id},
                    )
                    session.commit()
                upserted += len(page.items)
                cursor = page.next_cursor
                if page.exhausted or cursor is None:
                    break
        with session_factory() as session:
            done = session.get(Account, account_id)
            done.label_backfill_completed_at = datetime.now(timezone.utc)
            session.commit()
        return BackfillResult(account_id, "completed", len(folders), upserted)
    except Exception as exc:
        LOG.warning("label backfill failed account=%s: %s", account_id, exc)
        return BackfillResult(account_id, "failed", len(folders), upserted, str(exc))
    finally:
        with session_factory() as session:
            try:
                release_lease(
                    session,
                    account_id=account_id,
                    owner_id=owner_id,
                    fencing_token=lease.fencing_token,
                )
                session.commit()
            except Exception:
                session.rollback()
