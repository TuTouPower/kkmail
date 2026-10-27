"""Application-layer blob encryption (AES-256-GCM) with key versions.

Wire format (chunked AEAD, streamable; one format, no plaintext fallback):
  header  = magic(4)=b'KKMS' | key_version(u32 BE) | nonce_prefix(8)
  frame_i = ct_len(u32 BE) | AES-GCM(plaintext chunk ≤ 64 KiB)
  nonce_i = nonce_prefix | i(u32 BE);  AAD_i = header | i(u32 BE) | final(u8)
The final flag in the AAD makes truncation / frame reordering detectable.
Payloads without the magic are rejected (BlobCryptoError).

Plaintext SHA-256 remains the content-address key (architecture §10.2).
Keys are loaded from MAIL_CORE_BLOB_KEYS JSON: {"1": "<base64 32-byte key>", ...}
or MAIL_CORE_BLOB_KEY_V1 as a single base64 key for version 1.

No deterministic/dev fallback: missing keys raise BlobCryptoError.
Generate a key with:
  python3 -c 'import os,base64; print(base64.b64encode(os.urandom(32)).decode())'
"""

from __future__ import annotations

import base64
import binascii
import json
import os
import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"KKMS"
NONCE_PREFIX_LEN = 8
HEADER_LEN = 4 + 4 + NONCE_PREFIX_LEN
CHUNK_SIZE = 64 * 1024
TAG_LEN = 16


class BlobCryptoError(Exception):
    pass


class BlobIntegrityError(BlobCryptoError):
    """Stored blob format, authentication, or content digest verification failed."""


@dataclass(frozen=True, slots=True)
class Keyring:
    keys: dict[int, bytes]
    active_version: int

    def get(self, version: int) -> bytes:
        try:
            return self.keys[version]
        except KeyError as exc:
            raise BlobCryptoError(f"unknown blob key version {version}") from exc


def _b64key(raw: str, *, variable: str) -> bytes:
    try:
        key = base64.b64decode(raw, validate=True)
    except (binascii.Error, TypeError, ValueError) as exc:
        raise BlobCryptoError(f"{variable} must contain valid base64") from exc
    if len(key) != 32:
        raise BlobCryptoError(f"{variable} must encode 32 bytes (AES-256)")
    return key


def load_keyring_from_env(env: dict[str, str] | None = None) -> Keyring:
    if env is None:
        env = os.environ
    keys: dict[int, bytes] = {}
    blob = env.get("MAIL_CORE_BLOB_KEYS")
    if blob:
        try:
            entries = json.loads(blob)
        except (json.JSONDecodeError, TypeError) as exc:
            raise BlobCryptoError("MAIL_CORE_BLOB_KEYS must contain a valid JSON object") from exc
        if not isinstance(entries, dict):
            raise BlobCryptoError("MAIL_CORE_BLOB_KEYS must contain a JSON object")
        for version_text, encoded_key in entries.items():
            try:
                version = int(version_text)
            except (TypeError, ValueError) as exc:
                raise BlobCryptoError("MAIL_CORE_BLOB_KEYS must use integer key versions") from exc
            keys[version] = _b64key(encoded_key, variable="MAIL_CORE_BLOB_KEYS")
    # Convenience single-key
    if env.get("MAIL_CORE_BLOB_KEY_V1"):
        key_v1 = _b64key(env["MAIL_CORE_BLOB_KEY_V1"], variable="MAIL_CORE_BLOB_KEY_V1")
        if 1 in keys and keys[1] != key_v1:
            raise BlobCryptoError("MAIL_CORE_BLOB_KEY_V1 conflicts with MAIL_CORE_BLOB_KEYS version 1")
        keys[1] = key_v1
    if not keys:
        raise BlobCryptoError(
            "blob encryption keys required: set MAIL_CORE_BLOB_KEYS "
            '(JSON {"1": "<base64 32-byte key>", ...}) or MAIL_CORE_BLOB_KEY_V1. '
            "Generate with: python3 -c 'import os,base64; "
            "print(base64.b64encode(os.urandom(32)).decode())'"
        )
    active_version_text = env.get("MAIL_CORE_BLOB_KEY_VERSION") or env.get("MAIL_CORE_BLOB_ACTIVE_VERSION")
    active_version_variable = (
        "MAIL_CORE_BLOB_KEY_VERSION"
        if env.get("MAIL_CORE_BLOB_KEY_VERSION")
        else "MAIL_CORE_BLOB_ACTIVE_VERSION"
    )
    try:
        active = int(active_version_text) if active_version_text else max(keys)
    except (TypeError, ValueError) as exc:
        raise BlobCryptoError(f"{active_version_variable} must be an integer") from exc
    if active not in keys:
        raise BlobCryptoError(f"active key version {active} missing from keyring")
    return Keyring(keys=keys, active_version=active)


def _aad(header: bytes, index: int, final: bool) -> bytes:
    return header + struct.pack(">IB", index, 1 if final else 0)


def _nonce(prefix: bytes, index: int) -> bytes:
    return prefix + struct.pack(">I", index)


def iter_wrap(chunks: Iterable[bytes], *, keyring: Keyring, key_version: int | None = None) -> Iterator[bytes]:
    """Encrypt an iterable of plaintext pieces into framed ciphertext pieces.

    Input pieces are sliced with memoryview views (A110): each plaintext
    byte is copied exactly once into the current chunk buffer, so a single
    oversized piece no longer degrades to O(n^2) remainder copying, and at
    most one chunk of plaintext is buffered at a time.
    """
    version = key_version if key_version is not None else keyring.active_version
    aead = AESGCM(keyring.get(version))
    prefix = os.urandom(NONCE_PREFIX_LEN)
    header = MAGIC + struct.pack(">I", version) + prefix
    yield header
    index = 0
    buf = bytearray()
    pending: memoryview | None = None
    it = iter(chunks)
    exhausted = False
    while True:
        # Fill buf to CHUNK_SIZE, slicing the pending piece by view so the
        # unconsumed remainder is never copied.
        while len(buf) < CHUNK_SIZE and not exhausted:
            if pending is None:
                try:
                    pending = memoryview(next(it))
                except StopIteration:
                    exhausted = True
                    break
                if len(pending) == 0:
                    pending = None
                    continue
            take = min(CHUNK_SIZE - len(buf), len(pending))
            buf += pending[:take]
            pending = pending[take:] if take < len(pending) else None
        # A frame is final only once the input is known to be exhausted;
        # a full buffer with input possibly remaining is emitted non-final
        # (an exact-multiple input then gets a trailing empty final frame,
        # matching the previous framing behaviour).
        final = exhausted
        piece = bytes(buf)
        buf.clear()
        ct = aead.encrypt(_nonce(prefix, index), piece, _aad(header, index, final))
        yield struct.pack(">I", len(ct)) + ct
        index += 1
        if final:
            return
        if index >= 0xFFFFFFFF:  # pragma: no cover - 256 TiB
            raise BlobCryptoError("blob too large")


def wrap(plaintext: bytes, *, keyring: Keyring, key_version: int | None = None) -> bytes:
    return b"".join(iter_wrap([plaintext], keyring=keyring, key_version=key_version))


def _read_exact(fh: BinaryIO, n: int) -> bytes:
    data = fh.read(n)
    if len(data) != n:
        raise BlobIntegrityError("ciphertext truncated")
    return data


def read_key_version(fh: BinaryIO) -> int:
    header = fh.read(HEADER_LEN)
    if len(header) < HEADER_LEN or header[:4] != MAGIC:
        raise BlobIntegrityError("not an encrypted kkmail blob (missing KKMS header)")
    return struct.unpack(">I", header[4:8])[0]


def iter_unwrap(fh: BinaryIO, *, keyring: Keyring) -> Iterator[bytes]:
    """Decrypt a framed blob incrementally (bounded memory: one chunk at a time)."""
    header = fh.read(HEADER_LEN)
    if len(header) < HEADER_LEN or header[:4] != MAGIC:
        raise BlobIntegrityError("not an encrypted kkmail blob (missing KKMS header)")
    version = struct.unpack(">I", header[4:8])[0]
    prefix = header[8:HEADER_LEN]
    aead = AESGCM(keyring.get(version))
    index = 0
    while True:
        raw_len = fh.read(4)
        if not raw_len:
            raise BlobIntegrityError("ciphertext truncated (no final frame)")
        (ct_len,) = struct.unpack(">I", _pad4(raw_len))
        if ct_len < TAG_LEN or ct_len > CHUNK_SIZE + TAG_LEN:
            raise BlobIntegrityError("invalid frame length")
        ct = _read_exact(fh, ct_len)
        try:
            pt = aead.decrypt(_nonce(prefix, index), ct, _aad(header, index, False))
            final = False
        except InvalidTag:
            try:
                pt = aead.decrypt(_nonce(prefix, index), ct, _aad(header, index, True))
            except InvalidTag as exc:
                raise BlobIntegrityError("blob authentication failed") from exc
            final = True
        yield pt
        index += 1
        if final:
            if fh.read(1):
                raise BlobIntegrityError("trailing data after final frame")
            return


def _pad4(raw: bytes) -> bytes:
    if len(raw) != 4:
        raise BlobIntegrityError("ciphertext truncated")
    return raw


def unwrap(payload: bytes, *, keyring: Keyring) -> tuple[bytes, int]:
    import io

    fh = io.BytesIO(payload)
    version = read_key_version(fh)
    fh.seek(0)
    return b"".join(iter_unwrap(fh, keyring=keyring)), version
