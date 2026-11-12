"""Adoption fixes for the sync backend review (failure-domain isolation).

Background isolation is expressed either through ``SyncRequest.scope``
``background`` lineage (resolved via ``request_id``) or through an explicit
top-level ``background`` marker on silent/periodic jobs.  Account failures are
classified orthogonally by ``account_failure_kind`` so that a transport blip
can never be mistaken for an invalid credential.  The previous
MagicMock-based tests asserted a since-deleted ``_is_background_sync`` helper
and a single ``account_sync_failure_status`` enum; their semantics no longer
exist, so they were rewritten rather than having their expectations nudged to
the new output.  The real create/discovery/handler chain is covered by
test_sync_background_lineage.py.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

from mail_core.db.session import get_session_factory
from mail_core.sync.context import (
    AccountFailureKind,
    account_failure_kind,
    is_permanent_auth_error,
    resolve_sync_context,
    sync_context_payload,
)
from mail_core.mail.storage.models import SyncRequest, WorkerJob
from mail_core.providers.http import PermanentAuthError

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_NOW = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)


def test_explicit_background_marker_and_scope_lineage():
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
        # An explicit top-level marker is a first-class background source
        # (silent/periodic polling), independent of any request lineage.
        assert resolve_sync_context(session, WorkerJob(payload={"background": True})) == (True, None)
        assert resolve_sync_context(session, WorkerJob(payload={"request_id": str(bg_id)})) == (True, bg_id)
        assert resolve_sync_context(session, WorkerJob(payload={"request_id": str(fg_id)})) == (False, fg_id)
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


def test_account_failure_kind_is_orthogonal():
    # A confirmed auth rejection invalidates the credential everywhere.
    assert account_failure_kind(result=PermanentAuthError("x"), is_background=True) is AccountFailureKind.AUTH
    assert account_failure_kind(result=PermanentAuthError("x"), is_background=False) is AccountFailureKind.AUTH
    # A foreground transport blip degrades connectivity; a silent background
    # one never pollutes account health.
    blip = {"status": "provider_error", "error": "OSError code=101"}
    assert account_failure_kind(result=blip, is_background=False) is AccountFailureKind.TRANSPORT
    assert account_failure_kind(result=blip, is_background=True) is AccountFailureKind.NONE
    # Control-flow outcomes leave account health untouched.
    for result in ({"status": "lease_busy"}, {"status": "rate_limited"}, {"status": "provider_error"}):
        assert account_failure_kind(result=result, is_background=True) is AccountFailureKind.NONE
        assert account_failure_kind(result=result, is_background=False) is AccountFailureKind.NONE


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
