from __future__ import annotations

import base64
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select

from mail_core.blobs.crypto import MAGIC, BlobCryptoError, wrap
from mail_core.blobs.gc import sweep_expired_blobs
from mail_core.blobs.quota import acquire_blob_digest_lock
from mail_core.blobs.store import BlobStore
from mail_core.db.session import get_session_factory
from mail_core.mail.storage import MessageBlob


def test_blob_digest_lock_failure_is_logged_and_propagated(caplog):
    class Session:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, *_args, **_kwargs):
            raise RuntimeError("lock unavailable")

    caplog.set_level(logging.ERROR, logger="mail_core.blobs.quota")
    with pytest.raises(RuntimeError, match="lock unavailable"):
        acquire_blob_digest_lock(Session(), "a" * 64)

    assert "failed to acquire PostgreSQL blob digest advisory lock" in caplog.text


def test_blob_digest_lock_is_skipped_for_non_postgresql_dialects():
    class Session:
        bind = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        def execute(self, *_args, **_kwargs):
            pytest.fail("non-PostgreSQL sessions must not issue advisory locks")

    acquire_blob_digest_lock(Session(), "a" * 64)


def test_aes_gcm_roundtrip_and_key_version(tmp_path, monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.delenv("MAIL_CORE_BLOB_KEY_V1", raising=False)
    monkeypatch.setenv("MAIL_CORE_BLOB_KEYS", f'{{"1": "{key}", "2": "{base64.b64encode(os.urandom(32)).decode()}"}}')
    monkeypatch.setenv("MAIL_CORE_BLOB_KEY_VERSION", "1")
    store = BlobStore(tmp_path)
    data = b"MIME-Version: 1.0\r\n\r\nsecret-body"
    result = store.put(data)
    assert result.key_version == 1
    raw = (tmp_path / result.storage_path).read_bytes()
    assert raw.startswith(MAGIC)
    assert store.get(result.content_sha256) == data
    pt, ver = store.get_with_version(result.content_sha256)
    assert ver == 1 and pt == data
    # Non-KKMS payloads (e.g. plaintext) are rejected, never served.
    digest = store.hash_plaintext(b"legacy")
    path = store.path_for(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"legacy")
    with pytest.raises(BlobCryptoError):
        store.get(digest)


def test_streaming_roundtrip_large_and_tamper(tmp_path):
    store = BlobStore(tmp_path)
    data = os.urandom(3 * 64 * 1024 + 123)
    put = store.put(data)
    chunks = list(store.iter_plaintext(put.content_sha256))
    assert len(chunks) == 4 and max(len(c) for c in chunks) <= 64 * 1024
    assert b"".join(chunks) == data
    path = store.path_for(put.content_sha256)
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 0x01
    path.write_bytes(bytes(raw))
    with pytest.raises(BlobCryptoError):
        list(store.iter_plaintext(put.content_sha256))
    # Truncating whole trailing frames is detected via the final-frame flag.
    path.write_bytes(wrap(data, keyring=store.keyring)[: 16 + 4 + 64 * 1024 + 16])
    with pytest.raises(BlobCryptoError):
        list(store.iter_plaintext(put.content_sha256))


@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="PG required")
def test_delayed_gc_respects_cooloff(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    Session = get_session_factory()
    digest = uuid.uuid4().hex + uuid.uuid4().hex  # 64 hex, unique per run
    rel = f"{digest[:2]}/{digest[2:4]}/{digest}.blob"
    (tmp_path / digest[:2] / digest[2:4]).mkdir(parents=True)
    (tmp_path / rel).write_bytes(b"x")
    with Session() as session:
        blob = MessageBlob(
            content_sha256=digest,
            key_version=1,
            size_bytes=1,
            storage_path=rel,
            ref_count=0,
        )
        session.add(blob)
        session.commit()
        # cool-off not elapsed (gc_eligible_at stamped by mark_unreferenced)
        r1 = sweep_expired_blobs(session, cool_off=timedelta(hours=24), root=tmp_path)
        session.commit()
        assert r1.skipped_cooloff >= 1
        blob = session.scalar(select(MessageBlob).where(MessageBlob.content_sha256 == digest))
        assert blob is not None, "fresh blob must survive cool-off"
        assert blob.gc_eligible_at is not None
        # force cool-off elapsed via gc_eligible_at (not created_at)
        blob.gc_eligible_at = datetime.now(timezone.utc) - timedelta(hours=48)
        session.commit()
        r2 = sweep_expired_blobs(session, cool_off=timedelta(hours=24), root=tmp_path)
        paths = r2.paths_to_unlink
        session.commit()
        assert r2.deleted == 1
        # Phase 2 unlink after commit
        from mail_core.blobs.gc import unlink_gc_paths
        unlink_gc_paths(paths, root=tmp_path)
        assert not (tmp_path / rel).exists()


@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="PG required")
def test_mark_unreferenced_blobs_reconciles_in_bounded_id_pages(monkeypatch):
    from mail_core.blobs import gc as gc_mod

    monkeypatch.setattr(gc_mod, "_GC_RECONCILE_BATCH_SIZE", 2)
    Session = get_session_factory()
    now = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
    with Session() as session:
        blobs = [
            MessageBlob(
                content_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
                key_version=1,
                size_bytes=1,
                storage_path=f"gc-batch/{index}.blob",
                ref_count=3,
                gc_eligible_at=(now - timedelta(hours=1)) if index in (1, 3) else None,
            )
            for index in range(5)
        ]
        session.add_all(blobs)
        session.flush()

        select_statements = []

        def capture_blob_select(_conn, _cursor, statement, _params, _context, _many):
            normalized = " ".join(statement.lower().split())
            if normalized.startswith("select") and " from message_blobs " in normalized:
                select_statements.append((normalized, _params))

        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", capture_blob_select)
        try:
            marked = gc_mod.mark_unreferenced_blobs(session, now=now)
        finally:
            event.remove(engine, "before_cursor_execute", capture_blob_select)

        assert len(select_statements) == 4
        assert all(" limit " in statement for statement, _params in select_statements)
        assert all(
            2 in (params.values() if isinstance(params, dict) else params)
            for _statement, params in select_statements
        )
        assert marked == 8
        assert all(blob.ref_count == 0 for blob in blobs)
        assert [blob.gc_eligible_at for blob in blobs] == [
            now,
            now - timedelta(hours=1),
            now,
            now - timedelta(hours=1),
            now,
        ]
        session.commit()


def test_unlink_gc_paths_fails_closed_on_db_exception(tmp_path):
    from unittest.mock import MagicMock
    from mail_core.blobs.gc import unlink_gc_paths

    digest = "a" * 64
    fake_file = BlobStore(tmp_path).path_for(digest)
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_bytes(b"important data")

    broken_session = MagicMock()
    broken_session.scalar.side_effect = RuntimeError("DB connection dropped")

    unlinked_count = unlink_gc_paths([fake_file], session=broken_session, root=tmp_path)
    assert unlinked_count == 0
    # The file must NOT have been unlinked!
    assert fake_file.is_file()


def test_unlink_gc_paths_skips_non_digest_names_without_db_check(tmp_path):
    from unittest.mock import MagicMock
    from mail_core.blobs.gc import unlink_gc_paths

    fake_file = tmp_path / "unexpected-name.blob"
    fake_file.write_bytes(b"preserve")
    session = MagicMock()

    assert unlink_gc_paths([fake_file], session=session, root=tmp_path) == 0
    assert fake_file.is_file()
    session.scalar.assert_not_called()


def test_unlink_gc_paths_rejects_valid_digest_outside_blob_root(tmp_path):
    from unittest.mock import MagicMock
    from mail_core.blobs.gc import unlink_gc_paths

    digest = "b" * 64
    root = tmp_path / "blob-root"
    outside_root = tmp_path / "outside"
    root.mkdir()
    fake_file = BlobStore(outside_root).path_for(digest)
    fake_file.parent.mkdir(parents=True, exist_ok=True)
    fake_file.write_bytes(b"preserve")
    session = MagicMock()

    assert unlink_gc_paths([fake_file], session=session, root=root) == 0
    assert fake_file.is_file()
    session.scalar.assert_not_called()

