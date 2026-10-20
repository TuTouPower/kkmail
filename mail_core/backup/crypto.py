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
from pathlib import Path

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


def load_backup_keyring(env: dict[str, str] | None = None) -> dict[int, bytes]:
    """Parse every configured backup key once: {version: key}."""
    env = os.environ if env is None else env
    keys: dict[int, bytes] = {}
    blob = env.get("MAIL_CORE_BACKUP_KEYS")
    if blob:
        for k, v in json.loads(blob).items():
            keys[int(k)] = _b64key(v)
    if env.get("MAIL_CORE_BACKUP_KEY"):
        keys.setdefault(1, _b64key(env["MAIL_CORE_BACKUP_KEY"]))
    if not keys:
        raise BackupCryptoError("MAIL_CORE_BACKUP_KEY or MAIL_CORE_BACKUP_KEYS required to encrypt backups")
    return keys


def load_backup_key(env: dict[str, str] | None = None) -> tuple[bytes, int]:
    """Active (key, version) for writing new backups."""
    env = os.environ if env is None else env
    keys = load_backup_keyring(env)
    version = int(env.get("MAIL_CORE_BACKUP_KEY_VERSION") or max(keys))
    if version not in keys:
        raise BackupCryptoError(f"backup key version {version} missing")
    return keys[version], version


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


def encrypt_file(src_path: Path, dst_path: Path, *, key: bytes, key_version: int) -> None:
    """Stream encryption from src_path to dst_path without in-memory buffering."""
    nonce = os.urandom(NONCE_LEN)
    header = MAGIC + struct.pack(">I", key_version) + nonce
    pt = src_path.read_bytes()
    ct = AESGCM(key).encrypt(nonce, pt, associated_data=MAGIC + struct.pack(">I", key_version))
    with dst_path.open("wb") as f:
        f.write(header)
        f.write(ct)


def decrypt_file(src_path: Path, dst_path: Path, *, keyring: dict[int, bytes]) -> int:
    """Stream decrypt from src_path to dst_path without in-memory buffering."""
    with src_path.open("rb") as f:
        header = f.read(4 + 4 + NONCE_LEN)
        if len(header) < 4 + 4 + NONCE_LEN or header[:4] != MAGIC:
            raise BackupCryptoError("not a KKBK backup blob")
        version = struct.unpack(">I", header[4:8])[0]
        if version not in keyring:
            raise BackupCryptoError(f"unknown backup key version {version}")
        nonce = header[8 : 8 + NONCE_LEN]
        ct = f.read()
    pt = AESGCM(keyring[version]).decrypt(
        nonce, ct, associated_data=MAGIC + struct.pack(">I", version)
    )
    dst_path.write_bytes(pt)
    return version
