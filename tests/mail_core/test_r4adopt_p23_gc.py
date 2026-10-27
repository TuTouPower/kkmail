"""R4 adoption P23 (blob GC wave): A139 / A109 / A166 regression tests.

These use fake sessions so they run in unit mode without PostgreSQL.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from mail_core.blobs import gc as gc_mod


class _FakeScalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _FakeExecute:
    def all(self):
        return []


class FakeSession:
    """Serves pre-baked pages from scalars() and records flush/commit/delete."""

    def __init__(self, pages):
        self._pages = iter(pages)
        self.commits = 0
        self.flushes = 0
        self.deleted = []

    def scalars(self, _query):
        return _FakeScalars(next(self._pages, []))

    def execute(self, _query):
        return _FakeExecute()

    def flush(self):
        self.flushes += 1

    def commit(self):
        self.commits += 1

    def delete(self, obj):
        self.deleted.append(obj)


def _blob(blob_id: int, **overrides):
    base = dict(
        id=blob_id,
        ref_count=0,
        gc_eligible_at=None,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        content_sha256="a" * 64,
        storage_path="aa/aa/" + "a" * 64 + ".blob",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# --- A109: sweep_expired_blobs keyset-pages, commits per batch, canonical paths ---


def test_sweep_pages_and_uses_canonical_path_for_polluted_storage_path(tmp_path, monkeypatch):
    monkeypatch.setattr(gc_mod, "mark_unreferenced_blobs", lambda session, now=None: 0)
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    digest_a = "a" * 64
    digest_b = "b" * 64
    canonical_a = f"{digest_a[:2]}/{digest_a[2:4]}/{digest_a}.blob"
    b1 = _blob(1, gc_eligible_at=old, content_sha256=digest_a, storage_path=canonical_a)
    # storage_path polluted with traversal: sweep must derive the path from
    # the digest via BlobStore.path_for, never by joining the DB field.
    b2 = _blob(2, gc_eligible_at=old, content_sha256=digest_b, storage_path="../../evil.blob")
    # Unusable digest: cannot canonicalize, so the row must be skipped, not
    # deleted and not counted.
    b3 = _blob(3, gc_eligible_at=old, content_sha256="not-a-digest", storage_path="x/y/z.blob")
    session = FakeSession(pages=[[b1, b2], [b3], []])

    result = gc_mod.sweep_expired_blobs(
        session,
        cool_off=timedelta(hours=24),
        now=datetime(2026, 10, 25, tzinfo=timezone.utc),
        root=tmp_path,
    )

    from mail_core.blobs.store import BlobStore

    store = BlobStore(tmp_path)
    assert result.deleted == 2
    assert result.paths_to_unlink == (store.path_for(digest_a), store.path_for(digest_b))
    assert result.skipped_invalid == 1
    assert session.deleted == [b1, b2]
    assert session.commits == 2  # one commit per processed batch


# --- A139: mark_unreferenced_blobs dedupes marked and commits per page ---


def test_mark_counts_each_changed_blob_once_and_commits_per_page():
    stamped = datetime(2026, 1, 2, tzinfo=timezone.utc)
    b1 = _blob(1, ref_count=3, gc_eligible_at=None)  # ref change + stamp: one mark
    b2 = _blob(2, ref_count=0, gc_eligible_at=None)  # stamp only: one mark
    b3 = _blob(3, ref_count=0, gc_eligible_at=stamped)  # unchanged: no mark
    session = FakeSession(pages=[[b1, b2], [b3], []])

    marked = gc_mod.mark_unreferenced_blobs(session, now=datetime(2026, 10, 25, tzinfo=timezone.utc))

    assert marked == 2
    assert session.commits == 2  # one short transaction per non-empty page
    assert b1.ref_count == 0 and b1.gc_eligible_at is not None
    assert b3.gc_eligible_at == stamped
