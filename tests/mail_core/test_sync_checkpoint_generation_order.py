"""Checkpoint generation ordering: G1 -> G2 -> G1 must not regress.

``begin_scan_generation`` used ``!=`` to decide a generation change:
any different generation -- including an OLDER one whose job was
requeued (fail_job/reschedule return the payload, hence the old
``scan_generation``, untouched) -- reset the folder cursor and took
over the checkpoint. After the takeover, ``commit_checkpoint``'s
equality guard protected the stale generation and rejected the newer
one: exactly the inversion ``ScanGenerationMismatch`` exists to
prevent.

Root generations are allocated by ``create_sync_request`` and stamped
on the full request's targets (``requested_generation``), so a
generation's birth order is its earliest full-target ``created_at``
for the account. The pinned invariants:

* a generation with a LATER-born full-scan sibling is stale: its
  ``begin_scan_generation`` and ``commit_checkpoint`` raise
  ``ScanGenerationMismatch`` and the checkpoint row is untouched;
* the newest generation begins/commits normally, and same-generation
  retries keep the cursor;
* generations with no request record (legacy rows, direct engine use)
  keep the previous behaviour -- there is nothing to order them
  against.

Runs against the real PostgreSQL schema created by ``alembic upgrade head``
(UUID/JSONB/timestamptz); ``assert_fencing`` is patched out (the lease is
not under test). The fixed account/folder ids are seeded so the real FK
constraints on ``sync_checkpoints`` / ``sync_request_targets`` hold.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import Account, Folder, SyncCheckpoint, SyncRequest, SyncRequestTarget
from mail_core.sync import checkpoints as checkpoints_mod
from mail_core.sync.checkpoints import (
    ScanGenerationMismatch,
    begin_scan_generation,
    commit_checkpoint,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)

_T0 = datetime(2026, 10, 26, 12, 0, 0, tzinfo=timezone.utc)
_ACCOUNT = uuid.UUID("00000000-0000-0000-0000-00000000acc0")
_FOLDER = uuid.UUID("00000000-0000-0000-0000-00000000f01d")
_TOKEN = 7


def _seed_infra(Session):
    with Session() as session:
        session.add(
            Account(
                id=_ACCOUNT,
                email=f"gen-order-{uuid.uuid4().hex}@example.test",
                provider="imap",
                sync_enabled=True,
            )
        )
        session.add(
            Folder(
                id=_FOLDER,
                account_id=_ACCOUNT,
                remote_id="INBOX",
                name="INBOX",
                role="inbox",
            )
        )
        session.commit()


def _seed_full_generation(session, generation: uuid.UUID, *, born_at: datetime, target_id: uuid.UUID | None = None) -> None:
    """Record a full-scan root generation the way create_sync_request does."""
    request_id = uuid.uuid4()
    session.add(
        SyncRequest(
            id=request_id,
            client_request_id=f"gen-order-{uuid.uuid4().hex}",
            mode="full",
            trigger="manual",
            state="queued",
            scope={},
            created_at=born_at,
        )
    )
    session.add(
        SyncRequestTarget(
            id=target_id or uuid.uuid4(),
            request_id=request_id,
            account_id=_ACCOUNT,
            folder_id=_FOLDER,
            target_key=f"account:{_ACCOUNT}:folder:{_FOLDER}:role:inbox",
            requested_generation=generation,
            state="queued",
            created_at=born_at,
        )
    )
    session.flush()


@pytest.fixture(autouse=True)
def _no_fencing():
    with patch.object(checkpoints_mod, "assert_fencing", lambda *_a, **_k: None):
        yield


def _begin(session, generation):
    return begin_scan_generation(
        session,
        account_id=_ACCOUNT,
        folder_id=_FOLDER,
        fencing_token=_TOKEN,
        scan_generation=generation,
    )


def _commit(session, generation, cursor):
    return commit_checkpoint(
        session,
        account_id=_ACCOUNT,
        folder_id=_FOLDER,
        fencing_token=_TOKEN,
        cursor=cursor,
        scan_generation=generation,
    )


def _checkpoint(session) -> SyncCheckpoint:
    row = session.get(SyncCheckpoint, {"account_id": _ACCOUNT, "folder_id": _FOLDER})
    assert row is not None
    return row


def test_stale_generation_cannot_rebegin_or_commit_after_newer_generation():
    Session = get_session_factory()
    _seed_infra(Session)
    gen1, gen2 = uuid.uuid4(), uuid.uuid4()
    with Session() as session:
        _seed_full_generation(session, gen1, born_at=_T0)
        _begin(session, gen1)
        _commit(session, gen1, {"uid_next": 10})
        session.commit()

        _seed_full_generation(session, gen2, born_at=_T0 + timedelta(minutes=5))
        _begin(session, gen2)
        row = _checkpoint(session)
        assert row.scan_generation == gen2
        assert row.cursor == {}
        _commit(session, gen2, {"uid_next": 20})
        session.commit()

        with pytest.raises(ScanGenerationMismatch):
            _begin(session, gen1)
        session.rollback()
        row = _checkpoint(session)
        assert row.scan_generation == gen2
        assert row.cursor == {"uid_next": 20}

        with pytest.raises(ScanGenerationMismatch):
            _commit(session, gen1, {"uid_next": 999})
        session.rollback()
        row = _checkpoint(session)
        assert row.scan_generation == gen2
        assert row.cursor == {"uid_next": 20}

        _begin(session, gen2)
        row = _checkpoint(session)
        assert row.scan_generation == gen2
        assert row.cursor == {"uid_next": 20}
        _commit(session, gen2, {"uid_next": 30})
        session.commit()
        assert _checkpoint(session).cursor == {"uid_next": 30}


def test_unrecorded_generations_keep_legacy_behaviour():
    """Generations without a full-request record cannot be ordered;
    begin/commit keep the pre-fix semantics for them."""
    Session = get_session_factory()
    _seed_infra(Session)
    gen_a, gen_b = uuid.uuid4(), uuid.uuid4()
    with Session() as session:
        _begin(session, gen_a)
        _commit(session, gen_a, {"uid_next": 1})
        _begin(session, gen_b)
        row = _checkpoint(session)
        assert row.scan_generation == gen_b
        assert row.cursor == {}
        _commit(session, gen_b, {"uid_next": 2})
        session.commit()
        assert _checkpoint(session).cursor == {"uid_next": 2}


def test_same_timestamp_generations_are_ordered_by_stable_total_order():
    """A378: generations born in the same transaction share a
    ``created_at`` (Postgres ``now()`` is the transaction timestamp).
    With a strict ``birth > own_birth`` comparison neither generation
    is stale and the older one can take the checkpoint over. The birth
    key is therefore the stable total order ``(created_at, target id)``:
    the generation whose earliest target id is larger is the newer one.
    """
    Session = get_session_factory()
    _seed_infra(Session)
    gen_old, gen_new = uuid.uuid4(), uuid.uuid4()
    older_target = uuid.UUID("00000000-0000-0000-0000-000000000001")
    newer_target = uuid.UUID("00000000-0000-0000-0000-000000000002")
    with Session() as session:
        _seed_full_generation(session, gen_old, born_at=_T0, target_id=older_target)
        _seed_full_generation(session, gen_new, born_at=_T0, target_id=newer_target)
        session.commit()

        with pytest.raises(ScanGenerationMismatch):
            _begin(session, gen_old)
        session.rollback()
        with pytest.raises(ScanGenerationMismatch):
            _commit(session, gen_old, {"uid_next": 999})
        session.rollback()

        _begin(session, gen_new)
        _commit(session, gen_new, {"uid_next": 20})
        session.commit()
        row = _checkpoint(session)
        assert row.scan_generation == gen_new
        assert row.cursor == {"uid_next": 20}
