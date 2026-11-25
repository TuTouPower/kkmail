from __future__ import annotations

import errno
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mail_core.accounts import health
from mail_core.mail.domain.enums import (
    ConnectivityState,
    CredentialState,
    ExecutionOrigin,
    JobStatus,
    SyncActivity,
)
from mail_core.mail.storage.models import Account
from mail_core.providers.http import PermanentAuthError
from mail_core.security.redact import safe_provider_summary
from mail_core.sync.context import (
    AccountFailureKind,
    FailureDomain,
    account_failure_kind,
    classify_failure,
    resolve_sync_context,
)
from mail_core.sync.jobs import backoff_seconds, reschedule_job

_BASE = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)


class _FakeSession:
    def __init__(self, acc):
        self._acc = acc
        self.events = []

    def get(self, _model, _pk):
        return self._acc

    def add(self, event):
        self.events.append(event)

    def flush(self):
        pass


def _account() -> Account:
    acc = Account(email=f"health-{uuid.uuid4().hex[:8]}@example.test", provider="imap")
    acc.credential_state = CredentialState.VALID.value
    acc.connectivity_state = ConnectivityState.CONNECTED.value
    acc.sync_activity = SyncActivity.IDLE.value
    acc.config = {}
    return acc


def test_connectivity_failure_single_is_degraded():
    acc = _account()
    session = _FakeSession(acc)
    state = health.record_connectivity_failure(
        session, uuid.uuid4(), error="connection reset by peer", now=_BASE
    )
    assert state is ConnectivityState.DEGRADED
    assert acc.connectivity_state == ConnectivityState.DEGRADED.value
    assert acc.config[health.CFG_FAILURE_TIMESTAMPS] == [_BASE.isoformat()]
    expected = safe_provider_summary("connection reset by peer")
    assert acc.config[health.CFG_LAST_CONNECTIVITY_ERROR] == expected
    assert health.health_fields(acc)["last_connectivity_error"] == expected


def test_connectivity_failure_breaker_escalates_inside_window():
    acc = _account()
    session = _FakeSession(acc)
    for offset in (0, 60, 120, 180):
        state = health.record_connectivity_failure(
            session, uuid.uuid4(), error="timeout", now=_BASE + timedelta(seconds=offset)
        )
        assert state is ConnectivityState.DEGRADED
    window = health.CONNECTIVITY_WINDOW.total_seconds()
    state = health.record_connectivity_failure(
        session, uuid.uuid4(), error="timeout", now=_BASE + timedelta(seconds=window)
    )
    assert state is ConnectivityState.UNREACHABLE
    assert acc.connectivity_state == ConnectivityState.UNREACHABLE.value
    assert len(acc.config[health.CFG_FAILURE_TIMESTAMPS]) == health.CONNECTIVITY_FAILURE_THRESHOLD


def test_connectivity_failure_escalates_across_real_backoff_sequence():
    """p088 review: a real retry sequence must eventually reach unreachable."""

    acc = _account()
    session = _FakeSession(acc)
    elapsed = 0
    state = ConnectivityState.DEGRADED
    for attempt in range(1, 11):
        state = health.record_connectivity_failure(
            session, uuid.uuid4(), error="timeout", now=_BASE + timedelta(seconds=elapsed)
        )
        elapsed += backoff_seconds(attempt)
    assert state is ConnectivityState.UNREACHABLE
    assert acc.connectivity_state == ConnectivityState.UNREACHABLE.value


def test_connectivity_failure_does_not_accumulate_across_days():
    """p088: intermittent failures days apart must never reach unreachable."""

    acc = _account()
    session = _FakeSession(acc)
    for day in range(5):
        state = health.record_connectivity_failure(
            session, uuid.uuid4(), error="timeout", now=_BASE + timedelta(days=day)
        )
        assert state is ConnectivityState.DEGRADED
    assert acc.connectivity_state == ConnectivityState.DEGRADED.value
    assert len(acc.config[health.CFG_FAILURE_TIMESTAMPS]) == 1


def test_connectivity_transition_publishes_account_event():
    acc = _account()
    session = _FakeSession(acc)
    health.record_connectivity_failure(session, uuid.uuid4(), error="timeout", now=_BASE)
    assert len(session.events) == 1
    assert session.events[0].payload == {"connectivity_state": ConnectivityState.DEGRADED.value}
    health.record_connectivity_failure(session, uuid.uuid4(), error="timeout", now=_BASE)
    assert len(session.events) == 1
    health.record_connectivity_success(session, uuid.uuid4(), now=_BASE)
    assert len(session.events) == 2
    assert session.events[1].payload == {"connectivity_state": ConnectivityState.CONNECTED.value}


def test_unreachable_breaker_is_rechecked_after_a_bounded_interval():
    acc = _account()
    session = _FakeSession(acc)
    for offset in (0, 60, 120, 180, 300):
        health.record_connectivity_failure(
            session, uuid.uuid4(), error="timeout", now=_BASE + timedelta(seconds=offset)
        )
    assert acc.connectivity_state == ConnectivityState.UNREACHABLE.value
    assert health.recheck_unreachable(session, uuid.uuid4(), now=_BASE + timedelta(minutes=10)) is None
    assert health.recheck_unreachable(session, uuid.uuid4(), now=_BASE + timedelta(minutes=20)) is ConnectivityState.DEGRADED
    assert acc.connectivity_state == ConnectivityState.DEGRADED.value


def test_connectivity_success_closes_breaker_and_clears_diagnostics():
    acc = _account()
    session = _FakeSession(acc)
    for offset in (0, 60, 120, 180, 300):
        health.record_connectivity_failure(
            session, uuid.uuid4(), error="timeout", now=_BASE + timedelta(seconds=offset)
        )
    assert acc.connectivity_state == ConnectivityState.UNREACHABLE.value
    health.record_connectivity_success(
        session, uuid.uuid4(), now=_BASE + timedelta(seconds=360)
    )
    assert acc.connectivity_state == ConnectivityState.CONNECTED.value
    for key in (
        health.CFG_FAILURE_TIMESTAMPS,
        health.CFG_LAST_CONNECTIVITY_ERROR,
        "last_sync_error",
    ):
        assert key not in acc.config
    assert health.health_fields(acc)["last_connectivity_error"] is None


def test_credential_and_activity_state_machine():
    acc = _account()
    session = _FakeSession(acc)
    health.mark_credential_invalid(session, uuid.uuid4())
    assert acc.credential_state == CredentialState.INVALID.value
    assert acc.sync_enabled is False
    assert acc.sync_activity == SyncActivity.IDLE.value

    health.reset_credential(session, uuid.uuid4())
    assert acc.credential_state == CredentialState.VALID.value
    assert acc.sync_enabled is True

    health.set_sync_activity(session, uuid.uuid4(), active=True)
    assert acc.sync_activity == SyncActivity.SYNCING.value
    health.set_sync_activity(session, uuid.uuid4(), active=False)
    assert acc.sync_activity == SyncActivity.IDLE.value

    assert set(health.health_fields(acc)) == {
        "credential_state",
        "connectivity_state",
        "sync_activity",
        "last_connectivity_error",
    }


def test_account_failure_kind_classifies_transport_auth_and_control_flow():
    net = ConnectionError("connection reset by peer")
    assert account_failure_kind(result=net, is_background=False) is AccountFailureKind.TRANSPORT
    assert account_failure_kind(result=net, is_background=True) is AccountFailureKind.NONE
    assert account_failure_kind(
        result=PermanentAuthError("invalid_grant"), is_background=False
    ) is AccountFailureKind.AUTH
    assert account_failure_kind(
        result=PermanentAuthError("invalid_grant"), is_background=True
    ) is AccountFailureKind.AUTH
    assert account_failure_kind(
        result={"status": "rate_limited"}, is_background=False
    ) is AccountFailureKind.NONE


def test_failure_classification_ignores_free_text():
    """p088: non-network errors must not be promoted to transport failures."""

    assert classify_failure(OSError(28, "No space left on device")).domain is FailureDomain.UNKNOWN
    assert classify_failure(OSError(24, "Too many open files")).domain is FailureDomain.UNKNOWN
    assert classify_failure(OSError(13, "Permission denied")).domain is FailureDomain.UNKNOWN
    assert classify_failure(RuntimeError("DB connection string invalid")).domain is FailureDomain.UNKNOWN
    assert classify_failure(RuntimeError("service temporarily unavailable")).domain is FailureDomain.UNKNOWN
    assert classify_failure(
        {"status": "provider_error", "error": "ProviderHttpError status=401"}
    ).domain is FailureDomain.UNKNOWN
    assert classify_failure(OSError(errno.ECONNRESET, "Connection reset by peer")).domain is FailureDomain.TRANSPORT
    assert classify_failure(TimeoutError("timed out")).domain is FailureDomain.TRANSPORT


def test_resolve_sync_context_uses_typed_column_and_ignores_payload_marker():
    """t090: replaces legacy payload['background'] shim test.

    Execution lineage is stored exclusively in WorkerJob.execution_origin;
    without a linked request_id, resolving a WorkerJob requires no DB lookup
    and payload['background'] cannot spoof foreground into background.
    """

    class _NoDbSession:
        def get(self, *_args, **_kwargs):
            raise AssertionError("column-based lineage without request_id must not hit the DB")

    assert resolve_sync_context(
        _NoDbSession(),
        SimpleNamespace(execution_origin=ExecutionOrigin.BACKGROUND, payload={}),
    ) == (True, None)
    assert resolve_sync_context(
        _NoDbSession(),
        SimpleNamespace(execution_origin=ExecutionOrigin.FOREGROUND, payload={"background": True}),
    ) == (False, None)
    with pytest.raises(ValueError, match="execution_origin"):
        resolve_sync_context(_NoDbSession(), SimpleNamespace(payload={"background": True}))


def test_reschedule_job_count_failure_keeps_id_and_counts_failure():
    job = SimpleNamespace(
        id=uuid.uuid4(),
        status=JobStatus.CLAIMED.value,
        locked_by="w1",
        locked_at=_BASE,
        attempts=1,
        failure_attempts=0,
        last_error=None,
        payload={"folder_id": str(uuid.uuid4())},
        run_after=None,
        execution_generation=None,
        priority=55,
    )
    original_id = job.id
    reschedule_job(
        MagicMock(),
        job,
        worker_id="w1",
        count_failure=True,
        error="boom",
        now=_BASE,
    )
    assert job.id == original_id
    assert job.failure_attempts == 1
    assert job.status == JobStatus.PENDING.value
    # backoff_seconds(1) == 1s (hard-coded, not a self-referential assert).
    assert job.run_after == _BASE + timedelta(seconds=1)
    # The requeue keeps the original row, so priority survives; ``attempts``
    # is incremented by claim_jobs on the next claim, not by the requeue.
    assert job.priority == 55
    assert job.attempts == 1
    assert job.last_error


def test_auth_signals_are_classified_structurally():
    from mail_core.providers.http import PermanentAuthError, ProviderHttpError

    assert classify_failure(ProviderHttpError("boom", status=401)).domain is FailureDomain.AUTH
    assert classify_failure(PermanentAuthError("auth rejected")).domain is FailureDomain.AUTH
    assert classify_failure({"failure_code": "auth"}).domain is FailureDomain.AUTH
    assert classify_failure({"status": 401}).domain is FailureDomain.AUTH
    assert classify_failure(ConnectionError("connection reset")).domain is FailureDomain.TRANSPORT
    assert classify_failure({"status": "rate_limited"}).domain is FailureDomain.UNKNOWN
    assert classify_failure({"failure_code": "transport"}).domain is FailureDomain.TRANSPORT


def test_connectivity_breaker_negative_boundaries():
    # Fewer than five failures, even past the window, stays degraded.
    acc = _account()
    session = _FakeSession(acc)
    for offset in (0, 400):
        assert health.record_connectivity_failure(
            session, uuid.uuid4(), error="timeout", now=_BASE + timedelta(seconds=offset)
        ) is ConnectivityState.DEGRADED
    # Five failures inside the window but without spanning it stay degraded.
    acc2 = _account()
    session2 = _FakeSession(acc2)
    elapsed = 0
    for attempt in range(1, 6):
        assert health.record_connectivity_failure(
            session2, uuid.uuid4(), error="timeout", now=_BASE + timedelta(seconds=elapsed)
        ) is ConnectivityState.DEGRADED
        elapsed += backoff_seconds(attempt)
    assert acc2.connectivity_state == ConnectivityState.DEGRADED.value
