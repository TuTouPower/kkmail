"""Adoption fixes for the sync backend review (background isolation).

The payload ``background`` marker is gone: background isolation is a property
of ``SyncRequest.scope["background"]``, resolved through the ``request_id``
lineage in mail_core.sync.context. The previous
MagicMock-based tests asserted ``_is_background_sync(job)`` read that marker;
their semantics no longer exist, so they were deleted rather than having
their expectations rewritten to the new output. The real
create/discovery/handler chain is covered by test_sync_background_lineage.py.
The pure-function guard tests are kept unchanged; the one DB-backed
lineage test uses the real PostgreSQL session factory.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

from mail_core.db.session import get_session_factory
from mail_core.sync.context import (
    account_sync_failure_status,
    is_permanent_auth_error,
    resolve_sync_context,
    sync_context_payload,
)
from mail_core.mail.domain.enums import SyncStatus
from mail_core.mail.storage.models import SyncRequest, WorkerJob
from mail_core.providers.http import PermanentAuthError

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)


def test_payload_marker_is_never_a_background_source():
    Session = get_session_factory()
    fg_id, bg_id = uuid.uuid4(), uuid.uuid4()
    with Session() as session:
        session.add(
            SyncRequest(
                id=fg_id,
                client_request_id="fg",
                mode="delta",
                trigger="manual",
                state="queued",
                scope={"account_id": "x"},
                created_at=_NOW,
            )
        )
        session.add(
            SyncRequest(
                id=bg_id,
                client_request_id="bg",
                mode="delta",
                trigger="manual",
                state="queued",
                scope={"background": True},
                created_at=_NOW,
            )
        )
        session.commit()
        stale_marker = WorkerJob(payload={"request_id": str(fg_id), "background": True})
        assert resolve_sync_context(session, stale_marker) == (False, fg_id)
        clean_lineage = WorkerJob(payload={"request_id": str(bg_id)})
        assert resolve_sync_context(session, clean_lineage) == (True, bg_id)
        assert resolve_sync_context(session, WorkerJob(payload={})) == (False, None)


def test_sync_context_payload_never_emits_background_marker():
    rid = uuid.uuid4()
    payload = sync_context_payload(rid, folder_id="f", full=True)
    assert payload["request_id"] == str(rid)
    assert "background" not in payload


def test_is_permanent_auth_error_classifies_auth_vs_transient():
    assert is_permanent_auth_error(PermanentAuthError("rejected")) is True
    assert is_permanent_auth_error({"status": "auth_failed"}) is True
    assert is_permanent_auth_error({"error_code": "auth_failed"}) is True
    assert is_permanent_auth_error({"status": "rate_limited"}) is False
    assert is_permanent_auth_error(RuntimeError("transient")) is False


def test_account_sync_failure_status_is_single_decision():
    assert account_sync_failure_status(result=PermanentAuthError("x"), is_background=True) is SyncStatus.AUTH_FAILED
    assert account_sync_failure_status(result=PermanentAuthError("x"), is_background=False) is SyncStatus.AUTH_FAILED
    assert account_sync_failure_status(result={"status": "provider_error"}, is_background=True) is None
    assert account_sync_failure_status(result={"status": "lease_busy"}, is_background=True) is None
    assert account_sync_failure_status(result={"status": "rate_limited"}, is_background=True) is None
    assert account_sync_failure_status(result={"status": "provider_error"}, is_background=False) is SyncStatus.FAILED


def test_factory_does_not_import_dead_host_security_helpers():
    import mail_core.providers.factory as factory

    for name in ("is_private_host", "is_restricted_ip", "private_hosts_allowed"):
        assert not hasattr(factory, name)
    for name in ("is_loopback_host", "reject_microsoft_imap", "validate_imap_host"):
        assert hasattr(factory, name)


def test_background_discovery_skips_inbox_only():
    from mail_core.sync.engine import _should_enqueue_discovered_folder

    assert _should_enqueue_discovered_folder("inbox", background=False) is True
    assert _should_enqueue_discovered_folder("inbox", background=True) is False
    assert _should_enqueue_discovered_folder("sent", background=False) is True
    assert _should_enqueue_discovered_folder("sent", background=True) is True
    assert _should_enqueue_discovered_folder(None, background=True) is True
