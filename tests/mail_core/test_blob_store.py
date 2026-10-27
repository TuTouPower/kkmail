from mail_core.blobs import BlobStore


def test_put_get_roundtrip(tmp_path):
    store = BlobStore(tmp_path)
    data = b"MIME-Version: 1.0\r\n\r\nhello"
    result = store.put(data)
    assert len(result.content_sha256) == 64
    assert store.exists(result.content_sha256)
    assert store.get(result.content_sha256) == data
    # dedupe second put
    again = store.put(data)
    assert again.content_sha256 == result.content_sha256
    assert again.storage_path == result.storage_path


def test_put_returns_actual_disk_key_version(tmp_path, monkeypatch):
    import base64
    k1 = base64.b64encode(b"1" * 32).decode()
    k2 = base64.b64encode(b"2" * 32).decode()
    monkeypatch.delenv("MAIL_CORE_BLOB_KEY_V1", raising=False)
    monkeypatch.setenv("MAIL_CORE_BLOB_KEYS", f'{{"1": "{k1}", "2": "{k2}"}}')
    monkeypatch.setenv("MAIL_CORE_BLOB_KEY_VERSION", "1")
    store1 = BlobStore(tmp_path)
    data = b"MIME-Version: 1.0\r\n\r\nsome content"
    r1 = store1.put(data)
    assert r1.key_version == 1

    monkeypatch.setenv("MAIL_CORE_BLOB_KEY_VERSION", "2")
    store2 = BlobStore(tmp_path)
    r2 = store2.put(data)
    assert r2.key_version == 1  # Reports physical disk version, not active version 2!


def test_put_verifies_integrity_and_rewrites_corrupted_blob(tmp_path):
    store = BlobStore(tmp_path)
    data = b"Some test data for corruption self-healing"
    res1 = store.put(data)
    assert store.get(res1.content_sha256) == data

    # Intentionally corrupt the file on disk (truncate or overwrite with garbage)
    blob_file = store.path_for(res1.content_sha256)
    assert blob_file.is_file()
    blob_file.write_bytes(b"corrupted truncated data")

    # Calling put again on the same data should detect the corruption and rewrite the valid blob
    res2 = store.put(data)
    assert res2.content_sha256 == res1.content_sha256
    # Verify that get() now succeeds and returns the original data
    assert store.get(res2.content_sha256) == data


def test_put_rewrites_blob_with_unknown_key_version(tmp_path):
    # A138 采纳语义变更，替代旧 propagate 断言：put 统一捕获
    # BlobCryptoError 全族（含未知 key 版本的 plain BlobCryptoError），
    # 既存 blob 落入重写路径而非向上抛错、不替换。
    from mail_core.blobs.crypto import Keyring

    data = b"blob encrypted with a key version unavailable to this store"
    writer = BlobStore(tmp_path, keyring=Keyring({1: b"1" * 32}, active_version=1))
    result = writer.put(data)
    blob_path = writer.path_for(result.content_sha256)
    original_blob = blob_path.read_bytes()
    reader = BlobStore(tmp_path, keyring=Keyring({2: b"2" * 32}, active_version=2))

    # Must not raise BlobCryptoError: the existing blob is rewritten
    # under the reader's active key version.
    rewritten = reader.put(data)

    assert rewritten.content_sha256 == result.content_sha256
    assert rewritten.key_version == 2
    assert blob_path.read_bytes() != original_blob
    assert reader.get(rewritten.content_sha256) == data


def test_put_propagates_existing_blob_read_errors(tmp_path, monkeypatch):
    import pytest
    from pathlib import Path
    from mail_core.blobs.crypto import Keyring

    store = BlobStore(tmp_path, keyring=Keyring({1: b"k" * 32}, active_version=1))
    data = b"blob read errors must not be treated as corrupt content"
    result = store.put(data)
    blob_path = store.path_for(result.content_sha256)
    original_blob = blob_path.read_bytes()
    original_open = Path.open

    def fail_existing_blob_open(path, *args, **kwargs):
        if path == blob_path:
            raise PermissionError("blob read denied")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_existing_blob_open)
    with pytest.raises(PermissionError, match="blob read denied"):
        store.put(data)

    monkeypatch.setattr(Path, "open", original_open)
    assert blob_path.read_bytes() == original_blob
