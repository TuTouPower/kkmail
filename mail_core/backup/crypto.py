"""Separate backup-key encryption (architecture §11.1).

Backup key MUST NOT be the blob keyring. Load from MAIL_CORE_BACKUP_KEY
(base64 32-byte) or MAIL_CORE_BACKUP_KEYS JSON {"1": "..."}.

Wire format for ``*.kkbak``:
  magic(4)=b'KKBK' | key_version(u32 BE) | nonce(12) | AES-GCM(ciphertext of tar bytes)
"""

from __future__ import annotations

import base64
import json
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"KKBK"
NONCE_LEN = 12


class BackupCryptoError(Exception):
    pass


def _b64key(raw: str) -> bytes:
    key = base64.b64decode(raw)
    if len(key) != 32:
        raise BackupCryptoError("backup keys must be 32 bytes (AES-256)")
    return key


def load_backup_key(env: dict[str, str] | None = None) -> tuple[bytes, int]:
    env = env or os.environ
    keys: dict[int, bytes] = {}
    blob = env.get("MAIL_CORE_BACKUP_KEYS")
    if blob:
        for k, v in json.loads(blob).items():
            keys[int(k)] = _b64key(v)
    if env.get("MAIL_CORE_BACKUP_KEY"):
        keys.setdefault(1, _b64key(env["MAIL_CORE_BACKUP_KEY"]))
    if not keys:
        raise BackupCryptoError(
            "MAIL_CORE_BACKUP_KEY or MAIL_CORE_BACKUP_KEYS required to encrypt backups"
        )
    version = int(env.get("MAIL_CORE_BACKUP_KEY_VERSION") or max(keys))
    if version not in keys:
        raise BackupCryptoError(f"backup key version {version} missing")
    return keys[version], version


def load_backup_keyring(env: dict[str, str] | None = None) -> dict[int, bytes]:
    env = env or os.environ
    key, version = load_backup_key(env)
    keys = {version: key}
    blob = env.get("MAIL_CORE_BACKUP_KEYS")
    if blob:
        for k, v in json.loads(blob).items():
            keys[int(k)] = _b64key(v)
    if env.get("MAIL_CORE_BACKUP_KEY"):
        keys.setdefault(1, _b64key(env["MAIL_CORE_BACKUP_KEY"]))
    return keys


def encrypt_bytes(plaintext: bytes, *, key: bytes, key_version: int) -> bytes:
    nonce = os.urandom(NONCE_LEN)
    ct = AESGCM(key).encrypt(nonce, plaintext, associated_data=MAGIC + struct.pack(">I", key_version))
    return MAGIC + struct.pack(">I", key_version) + nonce + ct


def decrypt_bytes(payload: bytes, *, keyring: dict[int, bytes]) -> tuple[bytes, int]:
    if len(payload) < 4 + 4 + NONCE_LEN + 16 or payload[:4] != MAGIC:
        raise BackupCryptoError("not a KKBK backup blob")
    version = struct.unpack(">I", payload[4:8])[0]
    if version not in keyring:
        raise BackupCryptoError(f"unknown backup key version {version}")
    nonce = payload[8 : 8 + NONCE_LEN]
    ct = payload[8 + NONCE_LEN :]
    pt = AESGCM(keyring[version]).decrypt(
        nonce, ct, associated_data=MAGIC + struct.pack(">I", version)
    )
    return pt, version
