"""Package B (R04/R05/R18): archive claim ownership & failure convergence.

Covers repair_design §4:
- ArchiveClaim(message_id, owner, revision, remote_id_snapshot) is the only
  ownership token for success/error/quota/release/heartbeat writes.
- A stale execution (claim reclaimed, revision bumped) cannot publish,
  settle, release or heartbeat over the new owner's claim.
- Quota rejections (MIME reservation and attachment) converge to
  archive_paused_quota + pause_reason=quota with no NameError.
- Provider construction failure persists a sanitized last_error so the
  detail API's archive_has_error becomes true and explicit retry works.

The unit tests drive the real production functions through a stub session
(real two-session PostgreSQL competition lives in the PG-gated tests at the
bottom of this file, which run in CI where the owned PG runtime exists).
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import Update

import mail_core.blobs.archive as archive_mod
from mail_core.blobs.archive import (
    ArchiveClaim,
    heartbeat_archive_claims,
    run_archive_batch,
    settle_archive_claim,
)
from mail_core.mail.domain.enums import ArchiveState
from mail_core.mail.storage.models import (
    Account,
    Message,
    MessageArchiveState,
    MessageBody,
    OutboxEvent,
)


# ---------------------------------------------------------------------------
# Stub session: an in-memory stand-in that implements just the session
# surface the archive functions use (get / execute(Update|Select) / add /
# flush / commit / rollback / scalar / scalars) against shared row objects.
# ---------------------------------------------------------------------------


def _pk_of(obj) -> object | None:
    for attr in ("message_id", "id"):
        if hasattr(obj, attr):
            return getattr(obj, attr)
    return None


def _where_conds(stmt) -> dict:
    out: dict = {}

    def visit(expr):
        if hasattr(expr, "clauses"):
            for clause in expr.clauses:
                visit(clause)
        elif hasattr(expr, "left") and hasattr(expr, "right"):
            key = getattr(expr.left, "key", None)
            if key:
                out[key] = getattr(expr.right, "value", None)

    visit(stmt.whereclause)
    return out


class _Result:
    def __init__(self, rowcount=1):
        self.rowcount = rowcount


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class StubSession:
    def __init__(self, db: dict):
        self.db = db
        self.staged: list = []
        self.events: list = []
        self._new_keys: set = set()
        self.rolled_back = False
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

    @property
    def bind(self):
        return self.get_bind()

    def get(self, model, key):
        for obj in reversed(self.staged):
            if isinstance(obj, model) and _pk_of(obj) == key:
                return obj
        return self.db.get((model, key))

    def add(self, obj):
        if isinstance(obj, OutboxEvent):
            self.events.append(obj)
        self.staged.append(obj)

    def flush(self):
        for obj in self.staged:
            if type(obj).__name__ == "MessageBlob" and getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()
            key = (type(obj), _pk_of(obj))
            if key[1] is not None and key not in self.db:
                self.db[key] = obj
                self._new_keys.add(key)

    def commit(self):
        self.flush()
        self.committed = True
        self.staged.clear()
        self._new_keys.clear()

    def rollback(self):
        for key in self._new_keys:
            self.db.pop(key, None)
        self._new_keys.clear()
        self.staged.clear()
        self.rolled_back = True

    def execute(self, stmt):
        if isinstance(stmt, Update):
            conds = _where_conds(stmt)
            row = self.db.get((MessageArchiveState, conds.get("message_id")))
            if row is None:
                return _Result(0)
            for field in ("claimed_by", "claim_revision", "state"):
                if field in conds and getattr(row, field) != conds[field]:
                    return _Result(0)
            params = stmt.compile().params
            for field in ("claimed_at", "updated_at"):
                if field in params:
                    setattr(row, field, params[field])
            return _Result(1)
        return _Result(1)

    def scalar(self, stmt):
        return None

    def scalars(self, stmt):
        return _Scalars([])


def _make_rows(*, retry_count=0, revision=1, owner="worker-1"):
    acc_id = uuid.uuid4()
    mid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    msg = Message(id=mid, account_id=acc_id, remote_id="remote-1", subject="s", from_address="a@b.c")
    state = MessageArchiveState(
        message_id=mid,
        state=ArchiveState.ARCHIVE_IN_PROGRESS.value,
        claimed_by=owner,
        claim_revision=revision,
        retry_count=retry_count,
        claimed_at=now,
    )
    acc = Account(id=acc_id, email="t@example.com", provider="imap", credential_ref="cred-1", config={})
    db = {
        (Message, mid): msg,
        (MessageArchiveState, mid): state,
        (Account, acc_id): acc,
    }
    claim = ArchiveClaim(message_id=mid, owner=owner, revision=revision, remote_id_snapshot="remote-1")
    return db, claim, msg, state, acc


class FakeBlobStore:
    def __init__(self):
        self.put_calls = 0

    def exists(self, digest):
        return False

    def put(self, data):
        self.put_calls += 1
        return SimpleNamespace(
            size_bytes=len(data),
            content_sha256=hashlib.sha256(data).hexdigest(),
            key_version=1,
            storage_path="p",
        )


def _run_batch(db, claim, *, build_provider, blob_store=None, reserve_side_effect=None):
    """Drive run_archive_batch against the stub DB with patched seams."""
    blob_store = blob_store or FakeBlobStore()
    reserve_calls: list = []

    def _reserve(session, **kwargs):
        reserve_calls.append(kwargs)
        if reserve_side_effect is not None:
            return reserve_side_effect(len(reserve_calls))
        return uuid.uuid4()

    released: list = []

    def _release(session, reservation_id):
        released.append(reservation_id)

    fake_quota = SimpleNamespace(used_bytes=0, soft_exceeded=False, hard_exceeded=False)
    factory = lambda: StubSession(db)  # noqa: E731
    with (
        patch("mail_core.db.session.get_session_factory", return_value=factory),
        patch.object(archive_mod, "BlobStore", return_value=blob_store),
        patch.object(archive_mod, "check_quota", return_value=fake_quota),
        patch.object(archive_mod, "build_provider", build_provider),
        patch.object(archive_mod, "claim_archive_batch", return_value=[claim]),
        patch.object(archive_mod, "reserve_quota", side_effect=_reserve),
        patch.object(archive_mod, "release_quota_reservation", side_effect=_release),
        patch.object(archive_mod, "enqueue_job"),
    ):
        result = run_archive_batch(
            account_id=claim_account(db, claim),
            worker_id=claim.owner,
            payload={"batch_size": 1},
        )
    return result, reserve_calls, released


def claim_account(db, claim):
    msg = db[(Message, claim.message_id)]
    return msg.account_id


_SIMPLE_MIME = b"From: a@b.c\r\nSubject: s\r\nContent-Type: text/plain\r\n\r\nhello\r\n"
_MIME_WITH_ATT = (
    b"From: a@b.c\r\nSubject: s\r\nContent-Type: multipart/mixed; boundary=\"b\"\r\n\r\n"
    b"--b\r\nContent-Type: text/plain\r\n\r\nhello\r\n"
    b"--b\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=\"att.pdf\"\r\n\r\nPDF_DATA\r\n--b--"
)


# ---------------------------------------------------------------------------
# Unified settlement (R18 / R05) — unit level
# ---------------------------------------------------------------------------


def test_settle_provider_error_persists_sanitized_error_and_counts_retry():
    db, claim, _msg, state, _acc = _make_rows()
    session = StubSession(db)
    exc = RuntimeError("login failed password=hunter2 token=sekrit")
    applied = settle_archive_claim(session, claim, "provider_error", error=exc)
    assert applied is True
    assert state.state == ArchiveState.ARCHIVE_PENDING.value
    assert state.retry_count == 1
    assert state.last_error is not None and "RuntimeError" in state.last_error
    assert "hunter2" not in state.last_error and "sekrit" not in state.last_error
    assert state.claimed_by is None and state.claimed_at is None
    # Detail API derives archive_has_error from the persisted last_error.
    assert bool(state.last_error) is True
    assert session.events and session.events[0].payload["has_error"] is True
    assert session.events[0].payload["message_id"] == str(claim.message_id)


def test_settle_provider_error_exhausted_retries_lands_in_failed_with_error():
    db, claim, _msg, state, _acc = _make_rows(retry_count=4)
    session = StubSession(db)
    applied = settle_archive_claim(session, claim, "provider_error", error=RuntimeError("boom"))
    assert applied is True
    assert state.retry_count == 5
    assert state.state == ArchiveState.ARCHIVE_FAILED.value
    # After worker retries are exhausted the reader must still see the error
    # (archive_has_error) and the state must be explicitly retryable
    # (sync_message_body accepts ARCHIVE_FAILED -> ARCHIVE_PENDING).
    assert bool(state.last_error) is True


def test_settle_quota_pauses_without_counting_retry():
    db, claim, _msg, state, _acc = _make_rows(retry_count=2)
    session = StubSession(db)
    applied = settle_archive_claim(session, claim, "quota")
    assert applied is True
    assert state.state == ArchiveState.ARCHIVE_PAUSED_QUOTA.value
    assert state.pause_reason == "quota"
    assert state.retry_count == 2  # not an ordinary network failure
    assert state.claimed_by is None
    assert session.events[0].event_type == "archive.paused_quota"


def test_capacity_settlement_releases_without_counting_or_error_overwrite():
    db, claim, _msg, state, _acc = _make_rows(retry_count=1)
    state.last_error = "previous error"
    session = StubSession(db)
    applied = settle_archive_claim(session, claim, "capacity")
    assert applied is True
    assert state.state == ArchiveState.ARCHIVE_PENDING.value
    assert state.retry_count == 1
    assert state.last_error == "previous error"
    assert state.claimed_by is None


def test_stale_claim_cannot_settle_release_or_quota():
    """R04: worker2 reclaimed (revision 2); worker1's claim (revision 1)
    must not overwrite the new claim via any settlement outcome."""
    db, claim1, _msg, state, _acc = _make_rows(revision=1, owner="worker-1")
    # Simulate reclaim + re-claim by worker2.
    state.claimed_by = "worker-2"
    state.claim_revision = 2
    session = StubSession(db)
    for outcome in ("provider_error", "storage_error", "quota", "capacity", "release"):
        applied = settle_archive_claim(
            session, claim1, outcome, error=RuntimeError("stale failure")
        )
        assert applied is False, outcome
    assert state.state == ArchiveState.ARCHIVE_IN_PROGRESS.value
    assert state.claimed_by == "worker-2"
    assert state.claim_revision == 2
    assert state.retry_count == 0
    assert state.last_error is None
    assert session.events == []


def test_remote_id_change_invalidates_claim():
    db, claim, msg, state, _acc = _make_rows()
    msg.remote_id = "remote-2"  # remote identity changed since claim
    session = StubSession(db)
    applied = settle_archive_claim(session, claim, "provider_error", error=RuntimeError("x"))
    assert applied is False
    assert state.claimed_by == "worker-1"
    assert state.retry_count == 0


def test_heartbeat_refreshes_current_claim_and_rejects_stale_claim():
    db, claim, _msg, state, _acc = _make_rows()
    old_claimed_at = state.claimed_at
    session = StubSession(db)
    alive = heartbeat_archive_claims(session, [claim], now=old_claimed_at + timedelta(minutes=3))
    assert alive == [claim]
    assert state.claimed_at == old_claimed_at + timedelta(minutes=3)

    # Revoked: revision bumped and owner changed by the reclaimer.
    state.claim_revision = 2
    state.claimed_by = "worker-2"
    session2 = StubSession(db)
    alive2 = heartbeat_archive_claims(session2, [claim], now=old_claimed_at + timedelta(minutes=6))
    assert alive2 == []
    assert state.claimed_at == old_claimed_at + timedelta(minutes=3)  # untouched


# ---------------------------------------------------------------------------
# run_archive_batch convergence paths — unit level through production logic
# ---------------------------------------------------------------------------


def test_provider_construction_failure_persists_error_instead_of_silent_pending():
    """R18: build_provider raising must persist the sanitized error, count
    the retry, release the claim and emit the message event — not raise and
    not silently revert to pending (reader showed 'queued' forever)."""
    db, claim, _msg, state, _acc = _make_rows()

    def _build(*args, **kwargs):
        raise RuntimeError("credential decrypt failed password=hunter2")

    result, _res, _rel = _run_batch(db, claim, build_provider=_build)
    assert result["status"] == "ok"
    assert result["failed"] == 1
    assert state.state == ArchiveState.ARCHIVE_PENDING.value
    assert state.retry_count == 1
    assert state.last_error is not None and "RuntimeError" in state.last_error
    assert "hunter2" not in state.last_error
    assert state.claimed_by is None
    # Detail API: archive_has_error = bool(state.last_error)
    assert bool(state.last_error) is True


def test_mime_quota_reservation_failure_pauses_quota_without_nameerror():
    """R05: MIME reserve_quota -> None must produce archive_paused_quota
    (the removed `fencing` reference used to raise NameError here)."""
    db, claim, _msg, state, _acc = _make_rows()
    provider = SimpleNamespace(fetch_mime=lambda remote_id: _SIMPLE_MIME)
    result, _res, _rel = _run_batch(
        db, claim, build_provider=lambda *a, **kw: provider, reserve_side_effect=lambda n: None
    )
    assert result["status"] == "paused_quota"
    assert state.state == ArchiveState.ARCHIVE_PAUSED_QUOTA.value
    assert state.pause_reason == "quota"
    assert state.claimed_by is None
    assert state.retry_count == 0


def test_attachment_quota_failure_pauses_quota_without_nameerror():
    """R05: attachment reserve_quota -> None inside publish must roll back
    the derived transaction and quota-pause, again with no NameError."""
    db, claim, _msg, state, _acc = _make_rows()
    provider = SimpleNamespace(fetch_mime=lambda remote_id: _MIME_WITH_ATT)
    # 1st reservation (raw MIME) succeeds; 2nd (attachment) is rejected.
    result, reserve_calls, _rel = _run_batch(
        db,
        claim,
        build_provider=lambda *a, **kw: provider,
        reserve_side_effect=lambda n: uuid.uuid4() if n == 1 else None,
    )
    assert result["status"] == "paused_quota"
    assert len(reserve_calls) == 2
    assert state.state == ArchiveState.ARCHIVE_PAUSED_QUOTA.value
    assert state.pause_reason == "quota"
    assert state.claimed_by is None
    # Derived transaction was rolled back: no body row persisted.
    assert (MessageBody, claim.message_id) not in db


def test_stale_execution_does_not_publish_after_reclaim_during_fetch():
    """R04: worker2 reclaims the message while worker1 is fetching; when
    worker1 reaches the publish transaction its claim validation must fail
    and it must publish nothing (no body, no blob, no state overwrite)."""
    db, claim, _msg, state, _acc = _make_rows()
    blob_store = FakeBlobStore()

    def _fetch(remote_id):
        # Reclaimer revokes worker1's claim and worker2 takes it over.
        state.claimed_by = "worker-2"
        state.claim_revision = 2
        state.claimed_at = datetime.now(timezone.utc)
        return _SIMPLE_MIME

    provider = SimpleNamespace(fetch_mime=_fetch)
    # Isolate the publish-validation gate: heartbeat is driven separately in
    # test_heartbeat_refreshes_current_claim_and_rejects_stale_claim.
    with patch.object(
        archive_mod,
        "heartbeat_archive_claims",
        side_effect=lambda session, claims, **kw: list(claims),
    ):
        result, _res, released = _run_batch(
            db, claim, build_provider=lambda *a, **kw: provider, blob_store=blob_store
        )
    assert result["completed"] == 0
    assert blob_store.put_calls == 0
    assert (MessageBody, claim.message_id) not in db
    assert state.state == ArchiveState.ARCHIVE_IN_PROGRESS.value
    assert state.claimed_by == "worker-2"
    assert state.claim_revision == 2
    assert released  # this execution's quota reservation was released


def test_successful_publish_clears_error_and_pause_reason():
    db, claim, _msg, state, _acc = _make_rows()
    state.last_error = "old error"
    provider = SimpleNamespace(fetch_mime=lambda remote_id: _SIMPLE_MIME)
    result, _res, _rel = _run_batch(db, claim, build_provider=lambda *a, **kw: provider)
    assert result["status"] == "ok"
    assert result["completed"] == 1
    assert state.state == ArchiveState.ARCHIVE_COMPLETE.value
    assert state.last_error is None
    assert state.pause_reason is None
    assert state.claimed_by is None
    body = db.get((MessageBody, claim.message_id))
    assert body is not None and body.text_plain is not None and body.text_plain.strip() == "hello"


# ---------------------------------------------------------------------------
# PG-gated: real two-session claim competition (runs in CI's owned PG
# runtime; skipped honestly in unit mode where no database exists).
# ---------------------------------------------------------------------------

pg_only = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


@pg_only
def test_pg_two_session_claim_competition_old_worker_cannot_overwrite():
    from sqlalchemy import select

    from mail_core.accounts import DictCredentialStore, create_account, set_credential_store
    from mail_core.blobs.archive import claim_archive_batch, reclaim_stale_archive_claims
    from mail_core.db.session import get_session_factory

    Session = get_session_factory()
    store = DictCredentialStore({"r": "x"})
    set_credential_store(store)
    try:
        with Session() as session:
            acc = create_account(
                session,
                email=f"claim-race-{uuid.uuid4().hex[:8]}@example.com",
                provider="memory",
                credential_ref="r",
            )
            msg = Message(
                account_id=acc.id,
                remote_id="race-1",
                subject="Race",
                from_address="a@b.c",
                sort_time=datetime.now(timezone.utc),
            )
            session.add(msg)
            session.flush()
            session.add(
                MessageArchiveState(message_id=msg.id, state=ArchiveState.ARCHIVE_PENDING.value)
            )
            session.commit()
            mid, acc_id = msg.id, acc.id

        # Worker1 claims (revision 1).
        with Session() as s1:
            claims1 = claim_archive_batch(
                s1, account_id=acc_id, worker_id="worker-1", limit=1, recent_days=7,
                target_message_id=mid,
            )
            s1.commit()
        assert len(claims1) == 1
        claim1 = claims1[0]
        assert isinstance(claim1, ArchiveClaim)
        assert claim1.revision == 1
        assert claim1.remote_id_snapshot == "race-1"

        # Claim expires; the reclaimer revokes it (revision bumped).
        with Session() as s:
            st = s.get(MessageArchiveState, mid)
            st.claimed_at = datetime.now(timezone.utc) - timedelta(minutes=30)
            s.commit()
        with Session() as s:
            assert reclaim_stale_archive_claims(s, older_than=timedelta(minutes=15)) == 1
            s.commit()
            st = s.get(MessageArchiveState, mid)
            assert st.claim_revision == 2
            assert st.claimed_by is None

        # Worker2 reclaims (revision 3, owner worker-2).
        with Session() as s2:
            claims2 = claim_archive_batch(
                s2, account_id=acc_id, worker_id="worker-2", limit=1, recent_days=7,
                target_message_id=mid,
            )
            s2.commit()
        assert len(claims2) == 1
        claim2 = claims2[0]
        assert claim2.revision == 3 and claim2.owner == "worker-2"

        # Worker1 (stale) attempts success-adjacent settlements, error,
        # release, quota and heartbeat — none may touch worker2's claim.
        with Session() as s1:
            assert heartbeat_archive_claims(s1, [claim1]) == []
            s1.commit()
        for outcome in ("provider_error", "storage_error", "quota", "capacity", "release"):
            with Session() as s1:
                applied = settle_archive_claim(s1, claim1, outcome, error=RuntimeError("stale"))
                s1.commit()
            assert applied is False, outcome
        with Session() as s:
            st = s.get(MessageArchiveState, mid)
            assert st.state == ArchiveState.ARCHIVE_IN_PROGRESS.value
            assert st.claimed_by == "worker-2"
            assert st.claim_revision == 3
            assert st.retry_count == 0
            assert not st.last_error

        # Worker2's own settlement still applies.
        with Session() as s2:
            applied = settle_archive_claim(s2, claim2, "provider_error", error=RuntimeError("real"))
            s2.commit()
        assert applied is True
        with Session() as s:
            st = s.get(MessageArchiveState, mid)
            assert st.state == ArchiveState.ARCHIVE_PENDING.value
            assert st.retry_count == 1
            assert st.last_error and "RuntimeError" in st.last_error
    finally:
        set_credential_store(None)


# ---------------------------------------------------------------------------
# B4: open_session (provider handshake) failures
# ---------------------------------------------------------------------------


def test_open_session_capacity_error_settles_whole_batch_as_capacity():
    """B4: a CAPACITY_ERROR raised by open_session must not be swallowed by
    the handshake's blanket except — it reaches the batch-level capacity
    settlement (claims released, no retry counted, no error persisted),
    and the unconnected provider is never used for a fetch."""
    from mail_core.providers.connection_slots import ProviderCapacityUnavailable

    db, claim, _msg, state, _acc = _make_rows()
    fetch_calls: list = []

    class CapacityProvider:
        def open_session(self):
            raise ProviderCapacityUnavailable("pool exhausted")

        def fetch_mime(self, remote_id):
            fetch_calls.append(remote_id)
            return _SIMPLE_MIME

    result, _res, _rel = _run_batch(db, claim, build_provider=lambda *a, **kw: CapacityProvider())
    assert result["status"] == "capacity_unavailable"
    assert result["deferred"] == 1
    assert fetch_calls == []
    assert state.state == ArchiveState.ARCHIVE_PENDING.value
    assert state.retry_count == 0
    assert state.last_error is None
    assert state.claimed_by is None


def test_open_session_failure_is_not_cached_and_settles_provider_error():
    """B4: a non-capacity handshake failure must not cache the unconnected
    provider; the account's claims converge through the unified
    provider_error settlement (sanitized error persisted, retry counted),
    exactly like a build_provider construction failure."""
    db, claim, _msg, state, _acc = _make_rows()
    fetch_calls: list = []
    closed: list = []

    class BrokenHandshakeProvider:
        def open_session(self):
            raise RuntimeError("login failed password=<redacted>")

        def close_session(self):
            closed.append(True)

        def fetch_mime(self, remote_id):
            fetch_calls.append(remote_id)
            return _SIMPLE_MIME

    result, _res, _rel = _run_batch(
        db, claim, build_provider=lambda *a, **kw: BrokenHandshakeProvider()
    )
    assert result["status"] == "ok"
    assert result["failed"] == 1
    assert fetch_calls == [], "unhandshaked provider was used for a fetch"
    assert closed == [True], "partial session was not closed on handshake failure"
    assert state.state == ArchiveState.ARCHIVE_PENDING.value
    assert state.retry_count == 1
    assert state.last_error is not None and "RuntimeError" in state.last_error
    assert "hunter2" not in state.last_error
