from __future__ import annotations

import base64
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from mail_core.backup.crypto import (
    CHUNK_SIZE,
    MAGIC,
    BackupCryptoError,
    decrypt_bytes,
    decrypt_file,
    encrypt_bytes,
    encrypt_file,
    load_backup_key,
    load_backup_keyring,
)


@pytest.mark.parametrize(
    "env",
    [
        {"MAIL_CORE_BACKUP_KEYS": "{"},
        {"MAIL_CORE_BACKUP_KEYS": "[]"},
        {"MAIL_CORE_BACKUP_KEYS": '{"bad-version": "AA=="}'},
        {"MAIL_CORE_BACKUP_KEYS": '{"1": "%"}'},
    ],
)
def test_load_backup_keyring_rejects_malformed_configuration(env):
    with pytest.raises(BackupCryptoError, match="MAIL_CORE_BACKUP_KEYS"):
        load_backup_keyring(env)


def test_load_backup_key_rejects_malformed_active_version():
    key = base64.b64encode(os.urandom(32)).decode()
    with pytest.raises(BackupCryptoError, match="MAIL_CORE_BACKUP_KEY_VERSION"):
        load_backup_key({"MAIL_CORE_BACKUP_KEY": key, "MAIL_CORE_BACKUP_KEY_VERSION": "invalid"})


def test_crypto_streaming_roundtrip_chunked(tmp_path):
    key = os.urandom(32)
    key_version = 1
    keyring = {1: key}

    # Generate data larger than CHUNK_SIZE (256 KB + 123 bytes)
    plaintext = os.urandom(256 * 1024 + 123)
    src_path = tmp_path / "large_input.bin"
    src_path.write_bytes(plaintext)

    dst_enc = tmp_path / "backup.kkbak"
    encrypt_file(src_path, dst_enc, key=key, key_version=key_version)

    assert dst_enc.is_file()
    assert dst_enc.read_bytes()[:4] == MAGIC
    assert (dst_enc.stat().st_mode & 0o777) == 0o600

    dst_dec = tmp_path / "restored.bin"
    version = decrypt_file(dst_enc, dst_dec, keyring=keyring)
    assert version == key_version
    assert dst_dec.is_file()
    assert (dst_dec.stat().st_mode & 0o777) == 0o600
    assert dst_dec.read_bytes() == plaintext


def test_crypto_format_compatibility_with_bytes(tmp_path):
    key = os.urandom(32)
    keyring = {2: key}
    data = b"compatibility test string across streaming and in-memory encrypt/decrypt"

    # Case 1: encrypt_bytes -> decrypt_file
    blob = encrypt_bytes(data, key=key, key_version=2)
    enc_file = tmp_path / "from_bytes.kkbak"
    enc_file.write_bytes(blob)

    dec_file = tmp_path / "from_bytes.dec"
    ver = decrypt_file(enc_file, dec_file, keyring=keyring)
    assert ver == 2
    assert dec_file.read_bytes() == data

    # Case 2: encrypt_file -> decrypt_bytes
    src_file = tmp_path / "to_bytes.src"
    src_file.write_bytes(data)
    enc_file2 = tmp_path / "from_file.kkbak"
    encrypt_file(src_file, enc_file2, key=key, key_version=2)

    dec_bytes, ver2 = decrypt_bytes(enc_file2.read_bytes(), keyring=keyring)
    assert ver2 == 2
    assert dec_bytes == data


@pytest.mark.parametrize("size", [0, 64 * 1024, 64 * 1024 + 1])
def test_crypto_streaming_boundary_sizes(tmp_path, size):
    key = os.urandom(32)
    keyring = {1: key}
    data = os.urandom(size)

    src = tmp_path / f"input_{size}.bin"
    src.write_bytes(data)
    dst_enc = tmp_path / f"output_{size}.kkbak"
    dst_dec = tmp_path / f"output_{size}.dec"

    encrypt_file(src, dst_enc, key=key, key_version=1)
    decrypt_file(dst_enc, dst_dec, keyring=keyring)
    assert dst_dec.read_bytes() == data


def test_crypto_tamper_detection_and_no_plaintext_leak(tmp_path):
    key = os.urandom(32)
    keyring = {1: key}
    plaintext = b"sensitive payload that must never be exposed if tampered" * 100

    src = tmp_path / "secret.bin"
    src.write_bytes(plaintext)
    dst_enc = tmp_path / "secret.kkbak"
    encrypt_file(src, dst_enc, key=key, key_version=1)

    enc_bytes = bytearray(dst_enc.read_bytes())

    # Case 1: Tamper with ciphertext in the middle
    tampered_ct = bytearray(enc_bytes)
    tampered_ct[30] ^= 0xFF
    bad_enc1 = tmp_path / "bad_ct.kkbak"
    bad_enc1.write_bytes(tampered_ct)

    bad_dec1 = tmp_path / "bad_ct.dec"
    with pytest.raises(BackupCryptoError, match="tag verification failed"):
        decrypt_file(bad_enc1, bad_dec1, keyring=keyring)

    # Plaintext file must not be published
    assert not bad_dec1.exists()
    # No temporary files left behind in destination directory
    tmp_files = [f.name for f in tmp_path.iterdir() if f.name.startswith(".tmp_")]
    assert not tmp_files

    # Case 2: Tamper with 16-byte tag at the end
    tampered_tag = bytearray(enc_bytes)
    tampered_tag[-5] ^= 0xFF
    bad_enc2 = tmp_path / "bad_tag.kkbak"
    bad_enc2.write_bytes(tampered_tag)

    bad_dec2 = tmp_path / "bad_tag.dec"
    with pytest.raises(BackupCryptoError, match="tag verification failed"):
        decrypt_file(bad_enc2, bad_dec2, keyring=keyring)

    assert not bad_dec2.exists()
    tmp_files = [f.name for f in tmp_path.iterdir() if f.name.startswith(".tmp_")]
    assert not tmp_files


def test_crypto_truncated_file(tmp_path):
    key = os.urandom(32)
    keyring = {1: key}

    # Header truncation: less than 36 bytes
    trunc_short = tmp_path / "too_short.kkbak"
    trunc_short.write_bytes(MAGIC + b"\x00" * 10)
    out1 = tmp_path / "out1.bin"
    with pytest.raises(BackupCryptoError, match="not a KKBK backup blob"):
        decrypt_file(trunc_short, out1, keyring=keyring)
    assert not out1.exists()

    # Ciphertext truncation
    src = tmp_path / "input.bin"
    src.write_bytes(b"data to truncate" * 50)
    enc = tmp_path / "normal.kkbak"
    encrypt_file(src, enc, key=key, key_version=1)

    trunc_bytes = enc.read_bytes()[:-10]  # Cut off last 10 bytes
    trunc_file = tmp_path / "truncated.kkbak"
    trunc_file.write_bytes(trunc_bytes)

    out2 = tmp_path / "out2.bin"
    with pytest.raises(BackupCryptoError):
        decrypt_file(trunc_file, out2, keyring=keyring)
    assert not out2.exists()
    assert not [f for f in tmp_path.iterdir() if f.name.startswith(".tmp_")]


def test_crypto_wrong_key(tmp_path):
    key1 = os.urandom(32)
    key2 = os.urandom(32)

    src = tmp_path / "input.bin"
    src.write_bytes(b"some confidential data")
    enc = tmp_path / "enc.kkbak"
    encrypt_file(src, enc, key=key1, key_version=1)

    out = tmp_path / "out.bin"
    # Key version not in keyring
    with pytest.raises(BackupCryptoError, match="unknown backup key version"):
        decrypt_file(enc, out, keyring={2: key2})
    assert not out.exists()

    # Wrong key for version 1
    with pytest.raises(BackupCryptoError, match="tag verification failed"):
        decrypt_file(enc, out, keyring={1: key2})
    assert not out.exists()


def test_crypto_bounded_chunk_reads(tmp_path, monkeypatch):
    """Verify that file reads happen in fixed CHUNK_SIZE chunks rather than all-at-once."""
    import builtins
    key = os.urandom(32)
    total_size = CHUNK_SIZE * 3 + 500
    src = tmp_path / "large.bin"
    src.write_bytes(os.urandom(total_size))
    enc = tmp_path / "large.kkbak"

    read_sizes: list[int] = []

    class MonitoredFile:
        def __init__(self, raw_file):
            self._f = raw_file

        def read(self, size=-1):
            if size is not None and size > 0:
                read_sizes.append(size)
            return self._f.read(size)

        def seek(self, offset, whence=os.SEEK_SET):
            return self._f.seek(offset, whence)

        def tell(self):
            return self._f.tell()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self._f.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self._f, name)

    orig_path_open = Path.open

    def monitored_path_open(self, *args, **kwargs):
        f = orig_path_open(self, *args, **kwargs)
        if self.resolve() in (src.resolve(), enc.resolve()):
            return MonitoredFile(f)
        return f

    monkeypatch.setattr(Path, "open", monitored_path_open)

    encrypt_file(src, enc, key=key, key_version=1)
    assert all(s <= CHUNK_SIZE for s in read_sizes)
    assert len(read_sizes) >= 4

    read_sizes.clear()
    dec = tmp_path / "large.dec"
    decrypt_file(enc, dec, keyring={1: key})
    assert all(s <= CHUNK_SIZE for s in read_sizes)
    assert dec.read_bytes() == src.read_bytes()
