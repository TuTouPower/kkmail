"""Application-layer blob encryption (AES-256-GCM) with key versions.

Wire format (ciphertext file contents):
  magic(4)=b'KKMB' | key_version(u32 BE) | nonce(12) | ciphertext+tag

Plaintext SHA-256 remains the content-address key (architecture §10.2).
Keys are loaded from MAIL_CORE_BLOB_KEYS JSON: {"1": "<base64 32-byte key>", ...}
or MAIL_CORE_BLOB_KEY_V1 as a single base64 key for version 1.
"""

from __future__ import annotations

import base64
import json
import os
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"KKMB"
NONCE_LEN = 12


class BlobCryptoError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Keyring:
    keys: dict[int, bytes]
    active_version: int

    def get(self, version: int) -> bytes:
        try:
            return self.keys[version]
        except KeyError as exc:
            raise BlobCryptoError(f"unknown blob key version {version}") from exc


def _b64key(raw: str) -> bytes:
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise BlobCryptoError("blob keys must be 32 bytes (AES-256)")
    return key


def load_keyring_from_env(env: dict[str, str] | None = None) -> Keyring:
    env = env or os.environ
    keys: dict[int, bytes] = {}
    blob = env.get("MAIL_CORE_BLOB_KEYS")
    if blob:
        data = json.loads(blob)
        for k, v in data.items():
            keys[int(k)] = _b64key(v)
    # Convenience single-key
    if env.get("MAIL_CORE_BLOB_KEY_V1"):
        keys[1] = _b64key(env["MAIL_CORE_BLOB_KEY_V1"])
    if not keys:
        # Dev default — deterministic insecure key; override in production.
        keys[1] = hashlib_sha256_bytes(b"kkmail-dev-blob-key-v1")
    active = int(env.get("MAIL_CORE_BLOB_KEY_VERSION") or max(keys))
    if active not in keys:
        raise BlobCryptoError(f"active key version {active} missing from keyring")
    return Keyring(keys=keys, active_version=active)


def hashlib_sha256_bytes(data: bytes) -> bytes:
    import hashlib

    return hashlib.sha256(data).digest()


def wrap(plaintext: bytes, *, keyring: Keyring, key_version: int | None = None) -> bytes:
    version = key_version if key_version is not None else keyring.active_version
    key = keyring.get(version)
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, associated_data=MAGIC + struct.pack(">I", version))
    return MAGIC + struct.pack(">I", version) + nonce + ct


def unwrap(payload: bytes, *, keyring: Keyring) -> tuple[bytes, int]:
    if len(payload) < 4 or payload[:4] != MAGIC:
        # Legacy identity stub (pre-encryption) — treat as plaintext key_version=0
        return payload, 0
    if len(payload) < 4 + 4 + NONCE_LEN + 16:
        raise BlobCryptoError("ciphertext too short")
    version = struct.unpack(">I", payload[4:8])[0]
    nonce = payload[8 : 8 + NONCE_LEN]
    ct = payload[8 + NONCE_LEN :]
    key = keyring.get(version)
    pt = AESGCM(key).decrypt(nonce, ct, associated_data=MAGIC + struct.pack(">I", version))
    return pt, version
