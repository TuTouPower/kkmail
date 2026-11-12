from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from mail_core.accounts import health
from mail_core.mail.domain.enums import (
    ConnectivityState,
    CredentialState,
    JobStatus,
    SyncActivity,
)
from mail_core.mail.storage.models import Account
from mail_core.providers.http import PermanentAuthError
from mail_core.security.redact import safe_provider_summary
from mail_core.sync.context import (
    AccountFailureKind,
    account_failure_kind,
    resolve_sync_context,
)
from mail_core.sync.jobs import backoff_seconds, reschedule_job

_BASE = datetime(2026, 11, 9, 12, 0, 0, tzinfo=timezone.utc)


class _FakeSession:
    def __init__(self, acc):
        self._acc = acc

    def get(self, _model, _pk):
        return self._acc

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
    assert acc.config[health.CFG_FAILURE_COUNT] == 1
    assert acc.config[health.CFG_FIRST_FAILURE_AT] == _BASE.isoformat()
    expected = safe_provider_summary("connection reset by peer")
    assert acc.config[health.CFG_LAST_CONNECTIVITY_ERROR] == expected
    assert health.health_fields(acc)["last_connectivity_error"] == expected


def test_connectivity_failure_breaker_escalates_after_five_failures_across_window():
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
    assert acc.config[health.CFG_FAILURE_COUNT] == health.CONNECTIVITY_FAILURE_THRESHOLD


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
        health.CFG_FAILURE_COUNT,
        health.CFG_FIRST_FAILURE_AT,
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


def test_resolve_sync_context_reads_top_level_background_marker():
    class _NoDbSession:
        def get(self, *_args, **_kwargs):
            raise AssertionError("top-level background marker must not hit the DB")

    assert resolve_sync_context(
        _NoDbSession(), SimpleNamespace(payload={"background": True})
    ) == (True, None)
    assert resolve_sync_context(
        _NoDbSession(), SimpleNamespace(payload={"background": False})
    )[0] is False


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
    from mail_core.sync.context import is_permanent_auth_error

    # HTTP 401 is redacted to "ProviderHttpError status=401" upstream; both
    # the exception and the redacted summary must be recognised.
    assert is_permanent_auth_error(ProviderHttpError("boom", status=401)) is True
    assert is_permanent_auth_error(
        {"status": "provider_error", "error": "ProviderHttpError status=401"}
    ) is True
    # IMAP AUTHENTICATIONFAILED is normalised to PermanentAuthError upstream.
    assert is_permanent_auth_error(PermanentAuthError("auth rejected")) is True
    # delta.py / reconcile.py carry auth classification in a structured code.
    assert is_permanent_auth_error(
        {"status": "provider_error", "error_code": "auth_failed"}
    ) is True
    assert is_permanent_auth_error({"error": "token endpoint error: invalid_grant"}) is True
    assert is_permanent_auth_error({"error": "InvalidAuthenticationToken"}) is True
    # Transport blips and control-flow outcomes are never auth failures.
    assert is_permanent_auth_error(ConnectionError("connection reset")) is False
    assert is_permanent_auth_error({"status": "rate_limited"}) is False
    assert is_permanent_auth_error({"status": "provider_error", "error": "OSError code=101"}) is False


def test_connectivity_breaker_escalates_across_realistic_backoff():
    acc = _account()
    session = _FakeSession(acc)
    # Eight failures inside one job's exponential backoff sequence
    # (1,2,4,...,128s): all degraded, the count accumulates without reset.
    elapsed = 0
    for attempt in range(1, 9):
        assert health.record_connectivity_failure(
            session, uuid.uuid4(), error="timeout",
            now=_BASE + timedelta(seconds=elapsed),
        ) is ConnectivityState.DEGRADED
        elapsed += backoff_seconds(attempt)
    # A later periodic poll (20 min) with no success in between crosses the
    # window and reaches the threshold: unreachable is a live branch.
    assert health.record_connectivity_failure(
        session, uuid.uuid4(), error="timeout",
        now=_BASE + timedelta(seconds=20 * 60),
    ) is ConnectivityState.UNREACHABLE


def test_connectivity_breaker_negative_boundaries():
    # Fewer than five failures, even past the window, stays degraded.
    acc = _account()
    session = _FakeSession(acc)
    for offset in (0, 400):
        assert health.record_connectivity_failure(
            session, uuid.uuid4(), error="timeout",
            now=_BASE + timedelta(seconds=offset),
        ) is ConnectivityState.DEGRADED
    # Five failures inside the window (no 5-minute span) also stays degraded.
    acc2 = _account()
    session2 = _FakeSession(acc2)
    elapsed = 0
    for attempt in range(1, 6):
        assert health.record_connectivity_failure(
            session2, uuid.uuid4(), error="timeout",
            now=_BASE + timedelta(seconds=elapsed),
        ) is ConnectivityState.DEGRADED
        elapsed += backoff_seconds(attempt)
    assert acc2.connectivity_state == ConnectivityState.DEGRADED.value
