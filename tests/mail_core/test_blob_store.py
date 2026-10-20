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

