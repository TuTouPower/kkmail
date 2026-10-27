"""A110: iter_wrap must slice oversized input pieces instead of buffering
them whole, and BlobStore needs a streaming write path.

The old iter_wrap accumulated input into one bytearray and copied the
remainder on every frame (``del buf[:CHUNK_SIZE]`` after extending with a
potentially huge piece), so a single multi-MB chunk degraded to O(n^2)
copying and the whole plaintext stayed resident through wrap()/put().
"""

from __future__ import annotations

import base64

import pytest

from mail_core.blobs.crypto import CHUNK_SIZE, TAG_LEN, Keyring, iter_wrap, unwrap, wrap
from mail_core.blobs.store import BlobStore

_KEY = base64.b64decode(base64.b64encode(b"0123456789abcdef0123456789abcdef"))


def _keyring() -> Keyring:
    return Keyring(keys={1: _KEY}, active_version=1)


def test_iter_wrap_slices_single_huge_chunk_into_chunk_sized_frames():
    data = b"x" * (3 * CHUNK_SIZE + 123)
    pieces = list(iter_wrap([data], keyring=_keyring()))
    # header + at least 4 frames; no frame exceeds one chunk + length + tag.
    assert len(pieces) >= 5
    assert all(len(p) <= 4 + CHUNK_SIZE + TAG_LEN for p in pieces[1:])
    payload = b"".join(pieces)
    plain, _version = unwrap(payload, keyring=_keyring())
    assert plain == data


def test_iter_wrap_accepts_memoryview_and_generator_pieces():
    parts = [memoryview(b"a" * (CHUNK_SIZE + 5)), b"b" * 10, memoryview(b"c")]
    expected = b"a" * (CHUNK_SIZE + 5) + b"b" * 10 + b"c"
    payload = b"".join(iter_wrap(iter(parts), keyring=_keyring()))
    plain, _version = unwrap(payload, keyring=_keyring())
    assert plain == expected


def test_iter_wrap_empty_input_roundtrips():
    payload = b"".join(iter_wrap([], keyring=_keyring()))
    plain, _version = unwrap(payload, keyring=_keyring())
    assert plain == b""


def test_put_streaming_writes_large_blob_without_whole_bytes_api(tmp_path):
    store = BlobStore(tmp_path, keyring=_keyring())
    chunks = [b"m" * (2 * CHUNK_SIZE + 7), memoryview(b"n" * 999), b"o"]
    expected = b"".join(bytes(c) for c in chunks)
    result = store.put_streaming(iter(chunks))
    assert result.content_sha256 == store.hash_plaintext(expected)
    assert result.size_bytes == store.path_for(result.content_sha256).stat().st_size
    assert store.get(result.content_sha256) == expected


def test_put_streaming_matches_put_for_same_content(tmp_path):
    store = BlobStore(tmp_path, keyring=_keyring())
    data = b"same-content" * 5000
    via_put = store.put(data)
    via_stream = store.put_streaming([data[:1000], data[1000:]])
    assert via_stream.content_sha256 == via_put.content_sha256
    assert via_stream.size_bytes == via_put.size_bytes


def test_wrap_still_roundtrips():
    data = b"z" * (CHUNK_SIZE * 2 + 1)
    assert unwrap(wrap(data, keyring=_keyring()), keyring=_keyring())[0] == data
