"""A81: attachment downloads must not stream unverified plaintext.

``BlobStore.iter_plaintext`` yields each authenticated frame as it is
decrypted and only checks the content SHA-256 after the last chunk, so
a download built on it has already sent bytes before a digest mismatch
is discovered — bytes that cannot be taken back. The download path must
verify the whole blob first (spooling through a temp file keeps memory
bounded) and yield nothing when verification fails.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from mail_core.blobs.access import resolve_attachment_bytes
from mail_core.blobs.crypto import BlobIntegrityError
from mail_core.blobs.store import BlobStore
from mail_core.mail.storage.models import Attachment, MessageBlob


def _mismatched_copy(store: BlobStore, payload: bytes) -> str:
    stored = store.put(payload)
    wrong_digest = ("0" if stored.content_sha256[0] != "0" else "1") + stored.content_sha256[1:]
    wrong_path = store.path_for(wrong_digest)
    wrong_path.parent.mkdir(parents=True, exist_ok=True)
    wrong_path.write_bytes(store.path_for(stored.content_sha256).read_bytes())
    return wrong_digest


def test_verified_stream_roundtrip(tmp_path):
    store = BlobStore(tmp_path)
    data = b"verified-" * 20000  # spans multiple 64 KiB frames
    stored = store.put(data)
    assert b"".join(store.iter_plaintext_verified(stored.content_sha256)) == data


def test_verified_stream_yields_nothing_on_digest_mismatch(tmp_path):
    store = BlobStore(tmp_path)
    wrong_digest = _mismatched_copy(store, b"authenticated but addressed elsewhere")
    stream = store.iter_plaintext_verified(wrong_digest)
    # The very first pull must raise: no plaintext chunk may escape
    # before the digest check has completed.
    with pytest.raises(BlobIntegrityError, match="does not match its digest"):
        next(stream)


class _FakeSession:
    def __init__(self, att, blob):
        self._att = att
        self._blob = blob

    def get(self, model, _ident):
        return self._att if model is Attachment else self._blob


def _payload_for(store: BlobStore, digest: str):
    att = SimpleNamespace(
        id=uuid.uuid4(), message_id=uuid.uuid4(), blob_id=uuid.uuid4(),
        filename="a.bin", content_type="application/octet-stream", size_bytes=1,
    )
    blob = SimpleNamespace(id=att.blob_id, content_sha256=digest)
    session = _FakeSession(att, blob)
    return resolve_attachment_bytes(session, att.id, store=store)  # type: ignore[arg-type]


def test_attachment_open_stream_yields_nothing_on_digest_mismatch(tmp_path):
    store = BlobStore(tmp_path)
    wrong_digest = _mismatched_copy(store, b"attachment bytes under a wrong digest")
    # The file must exist under the claimed digest for access checks.
    payload = _payload_for(store, wrong_digest)
    stream = payload.open_stream()
    with pytest.raises(BlobIntegrityError):
        next(iter(stream))


def test_attachment_open_stream_roundtrip(tmp_path):
    store = BlobStore(tmp_path)
    data = b"real attachment"
    stored = store.put(data)
    payload = _payload_for(store, stored.content_sha256)
    assert b"".join(payload.open_stream()) == data
    # Silence unused-import lint for the model used in _FakeSession typing.
    assert MessageBlob is not None
