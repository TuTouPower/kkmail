from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.blobs.crypto import MAGIC, BlobCryptoError, wrap
from mail_core.blobs.gc import sweep_expired_blobs
from mail_core.blobs.store import BlobStore
from mail_core.db.session import get_session_factory
from mail_core.mail.storage import MessageBlob


def test_aes_gcm_roundtrip_and_key_version(tmp_path, monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
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
        unlink_gc_paths(paths)
        assert not (tmp_path / rel).exists()


def test_unlink_gc_paths_fails_closed_on_db_exception(tmp_path):
    from unittest.mock import MagicMock
    from mail_core.blobs.gc import unlink_gc_paths

    digest = "a" * 64
    fake_file = tmp_path / f"{digest}.blob"
    fake_file.write_bytes(b"important data")

    broken_session = MagicMock()
    broken_session.scalar.side_effect = RuntimeError("DB connection dropped")

    unlinked_count = unlink_gc_paths([fake_file], session=broken_session)
    assert unlinked_count == 0
    # The file must NOT have been unlinked!
    assert fake_file.is_file()

