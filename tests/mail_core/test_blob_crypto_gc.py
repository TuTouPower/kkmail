from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from mail_core.blobs.crypto import MAGIC, load_keyring_from_env, unwrap, wrap
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
    # identity legacy still readable
    legacy = tmp_path / "aa" / "bb" / ("c" * 64 + ".blob")
    # write legacy plaintext path via unwrap path: put file without magic
    digest = store.hash_plaintext(b"legacy")
    path = store.path_for(digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"legacy")
    assert store.get(digest) == b"legacy"


@pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), reason="PG required")
def test_delayed_gc_respects_cooloff(tmp_path, monkeypatch):
    monkeypatch.setenv("MAIL_CORE_BLOB_ROOT", str(tmp_path))
    Session = get_session_factory()
    digest = "a" * 64
    rel = f"aa/bb/{digest}.blob"
    (tmp_path / "aa" / "bb").mkdir(parents=True)
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
        # cool-off not elapsed
        r1 = sweep_expired_blobs(session, cool_off=timedelta(hours=24), root=tmp_path)
        session.commit()
        assert r1.deleted == 0
        assert r1.skipped_cooloff >= 1
        # force old created_at
        blob = session.scalar(select(MessageBlob).where(MessageBlob.content_sha256 == digest))
        blob.created_at = datetime.now(timezone.utc) - timedelta(hours=48)
        session.commit()
        r2 = sweep_expired_blobs(session, cool_off=timedelta(hours=24), root=tmp_path)
        session.commit()
        assert r2.deleted == 1
        assert not (tmp_path / rel).exists()
