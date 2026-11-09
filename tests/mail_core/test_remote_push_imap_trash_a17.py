"""A17: IMAP trash fallback must run for real ImapProvider-shaped providers.

The old gate read ``getattr(provider, "name", "") == "imap"``; real
providers have no ``name`` attribute, so the fallback never ran and ops
kept the literal ``"Trash"`` folder. Resolving the folder must also not
poison the settlement CAS: the claimed ``desired_state`` snapshot is what
the CAS compares against, so a locally resolved trash folder that leaks
into that snapshot makes every push look "modified during push" and
loops forever.

Runs against the real PostgreSQL schema created by ``alembic upgrade head``:
JSONB ``desired_state``, timestamptz ``updated_at`` (round-trips with
tzinfo, so the settlement CAS compares true instants) and FOR UPDATE row
locks are all exercised by the real ``push_remote_operations`` path.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mail_core.db.session import get_session_factory
from mail_core.mail.domain.enums import RemoteOperationStatus
from mail_core.mail.storage.models import Account, Folder, RemoteOperation
from mail_core.providers.imap import ImapProvider
from mail_core.sync import remote_push as remote_push_mod

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 10, 27, 12, 0, 0, tzinfo=timezone.utc)


def test_imap_trash_fallback_resolves_real_folder_and_settles_done():
    Session = get_session_factory()
    account_id = uuid.uuid4()
    op_id = uuid.uuid4()
    with Session() as session:
        session.add(
            Account(
                id=account_id, email="imap@example.test", provider="imap",
                credential_ref="ref", config={}, sync_enabled=True,
            )
        )
        session.add(
            Folder(
                id=uuid.uuid4(), account_id=account_id,
                remote_id="Papierkorb", name="Papierkorb", role="trash",
            )
        )
        session.add(
            RemoteOperation(
                id=op_id, account_id=account_id,
                entity_key="msg:msg-1:trash", op_type="trash",
                desired_state={
                    "remote_id": "msg-1", "folder_remote_id": "INBOX",
                    "trash_folder_remote_id": "Trash",
                },
                status=RemoteOperationStatus.PENDING.value,
                created_at=_NOW, updated_at=_NOW,
            )
        )
        session.commit()

    provider = ImapProvider(host="imap.example.test", port=993, username="u", password="p")
    assert not hasattr(provider, "name"), "real ImapProvider shape has no name attribute"
    seen: dict = {}

    def _apply_batch(operations):
        results = []
        for item in operations:
            seen["op_type"] = item.op_type
            seen["desired"] = dict(item.desired_state)
            results.append(
                (item.op_id, SimpleNamespace(success=True, error=None, remote_state={}))
            )
        return results

    provider.apply_remote_operations = _apply_batch  # type: ignore[method-assign]

    with patch.object(remote_push_mod, "build_provider", lambda *a, **k: provider):
        result = remote_push_mod.push_remote_operations(account_id, worker_id="w-a17", store=object())

    assert result["status"] == "ok"
    assert result["pushed"] == 1, f"op must settle DONE, not loop back to PENDING: {result}"
    assert seen["desired"]["trash_folder_remote_id"] == "Papierkorb"
    with Session() as session:
        op = session.get(RemoteOperation, op_id)
        assert op is not None and op.status == RemoteOperationStatus.DONE.value
