"""R4 adoption package P15 (blobs/archive)专项测试.

Unit-level: drives the real production functions in
``mail_core.blobs.archive`` through an in-memory stub session (same
approach as test_archive_claim_ownership.py); PG-gated paths are not
exercised here.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import Update

import mail_core.blobs.archive as archive_mod
from mail_core.blobs.archive import ArchiveClaim, run_archive_batch
from mail_core.mail.domain.enums import ArchiveState
from mail_core.mail.storage.models import (
    Account,
    Message,
    MessageArchiveState,
    MessageBody,
    OutboxEvent,
)


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


def _make_claim(db, acc_id, mid, remote_id, owner="worker-1"):
    now = datetime.now(timezone.utc)
    msg = Message(id=mid, account_id=acc_id, remote_id=remote_id, subject="s", from_address="a@b.c")
    state = MessageArchiveState(
        message_id=mid,
        state=ArchiveState.ARCHIVE_IN_PROGRESS.value,
        claimed_by=owner,
        claim_revision=1,
        retry_count=0,
        claimed_at=now,
    )
    db[(Message, mid)] = msg
    db[(MessageArchiveState, mid)] = state
    return ArchiveClaim(message_id=mid, owner=owner, revision=1, remote_id_snapshot=remote_id), msg, state


def _base_db():
    acc_id = uuid.uuid4()
    acc = Account(id=acc_id, email="t@example.com", provider="imap", credential_ref="cred-1", config={})
    return {(Account, acc_id): acc}, acc_id


class FakeBlobStore:
    """Blob store double; ``exists`` is controllable for dedup scenarios."""

    def __init__(self, *, exists=False, size_bytes=100):
        self._exists = exists
        self._size = size_bytes
        self.put_calls = 0

    def exists(self, digest):
        return self._exists

    def put(self, data):
        self.put_calls += 1
        return SimpleNamespace(
            size_bytes=self._size,
            content_sha256=hashlib.sha256(data).hexdigest(),
            key_version=1,
            storage_path="p",
        )


def _run_batch(db, claims, *, build_provider, blob_store=None, payload=None, quota_used=0):
    blob_store = blob_store or FakeBlobStore()
    fake_quota = SimpleNamespace(used_bytes=quota_used, soft_exceeded=False, hard_exceeded=False)
    factory = lambda: StubSession(db)  # noqa: E731
    account_id = db[(Message, claims[0].message_id)].account_id
    with (
        patch("mail_core.db.session.get_session_factory", return_value=factory),
        patch.object(archive_mod, "BlobStore", return_value=blob_store),
        patch.object(archive_mod, "check_quota", return_value=fake_quota),
        patch.object(archive_mod, "build_provider", build_provider),
        patch.object(archive_mod, "claim_archive_batch", return_value=list(claims)),
        patch.object(archive_mod, "reserve_quota", return_value=uuid.uuid4()),
        patch.object(archive_mod, "release_quota_reservation"),
        patch.object(archive_mod, "enqueue_job"),
        patch.object(archive_mod, "resume_quota_paused_archives", return_value=0),
    ):
        result = run_archive_batch(
            account_id=account_id,
            worker_id="worker-1",
            payload=payload if payload is not None else {"batch_size": len(claims)},
        )
    return result


_SIMPLE_MIME = b"From: a@b.c\r\nSubject: s\r\nContent-Type: text/plain\r\n\r\nhello\r\n"


# ---------------------------------------------------------------------------
# A16: dedup hits must not inflate current_used_bytes
# ---------------------------------------------------------------------------


def test_a16_dedup_hit_does_not_inflate_current_used_bytes():
    """Two messages whose MIME blob already exists on disk (dedup hit):
    put() returns the existing size but writes no new bytes, so the
    incremental quota tracker must stay at the pre-batch usage and the
    batch must not spuriously pause on the soft limit."""
    db, acc_id = _base_db()
    claims, states = [], []
    for i in range(2):
        claim, _msg, state = _make_claim(db, acc_id, uuid.uuid4(), f"remote-{i}")
        claims.append(claim)
        states.append(state)
    provider = SimpleNamespace(fetch_mime=lambda remote_id: _SIMPLE_MIME)
    result = _run_batch(
        db,
        claims,
        build_provider=lambda *a, **kw: provider,
        blob_store=FakeBlobStore(exists=True, size_bytes=100),
        # Soft limit 90 < one (phantom) blob of 100: a single double-count
        # would pause the batch before the second message.
        payload={"batch_size": 2, "soft_limit_bytes": 90},
    )
    assert result["status"] == "ok"
    assert result["completed"] == 2
    assert all(s.state == ArchiveState.ARCHIVE_COMPLETE.value for s in states)
