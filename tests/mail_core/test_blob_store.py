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
