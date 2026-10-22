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
import uuid
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"KKBK"
NONCE_LEN = 12
HEADER_LEN = 4 + 4 + NONCE_LEN  # 20 bytes
TAG_LEN = 16  # AES-GCM authentication tag length
MIN_PAYLOAD_LEN = HEADER_LEN + TAG_LEN  # 36 bytes
CHUNK_SIZE = 64 * 1024  # 64 KB streaming buffer


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
    if not src_path.is_file():
        raise BackupCryptoError(f"source file not found: {src_path}")
    nonce = os.urandom(NONCE_LEN)
    aad = MAGIC + struct.pack(">I", key_version)
    header = aad + nonce

    cipher = Cipher(algorithms.AES(key), modes.GCM(nonce))
    encryptor = cipher.encryptor()
    encryptor.authenticate_additional_data(aad)

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dst = dst_path.parent / f".tmp_{dst_path.name}_{uuid.uuid4().hex}"
    try:
        fd = os.open(temp_dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f_out:
            f_out.write(header)
            with src_path.open("rb") as f_in:
                while True:
                    chunk = f_in.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    ct_chunk = encryptor.update(chunk)
                    if ct_chunk:
                        f_out.write(ct_chunk)
            final_ct = encryptor.finalize()
            if final_ct:
                f_out.write(final_ct)
            f_out.write(encryptor.tag)
            f_out.flush()
            os.fsync(f_out.fileno())

        os.replace(temp_dst, dst_path)
        try:
            os.chmod(dst_path, 0o600)
        except OSError:
            pass
    finally:
        if temp_dst.exists():
            try:
                temp_dst.unlink()
            except OSError:
                pass


def decrypt_file(src_path: Path, dst_path: Path, *, keyring: dict[int, bytes]) -> int:
    """Stream decrypt from src_path to dst_path without in-memory buffering."""
    if not src_path.is_file():
        raise BackupCryptoError(f"source file not found: {src_path}")

    with src_path.open("rb") as f_in:
        f_in.seek(0, os.SEEK_END)
        src_size = f_in.tell()
        if src_size < MIN_PAYLOAD_LEN:
            raise BackupCryptoError("not a KKBK backup blob")

        f_in.seek(0, os.SEEK_SET)
        header = f_in.read(HEADER_LEN)
        if len(header) < HEADER_LEN or header[:4] != MAGIC:
            raise BackupCryptoError("not a KKBK backup blob")
        version = struct.unpack(">I", header[4:8])[0]
        if version not in keyring:
            raise BackupCryptoError(f"unknown backup key version {version}")
        nonce = header[8:HEADER_LEN]

        f_in.seek(-TAG_LEN, os.SEEK_END)
        tag = f_in.read(TAG_LEN)
        if len(tag) < TAG_LEN:
            raise BackupCryptoError("truncated backup blob: missing tag")

        ct_total = src_size - MIN_PAYLOAD_LEN
        f_in.seek(HEADER_LEN, os.SEEK_SET)

        key = keyring[version]
        aad = MAGIC + struct.pack(">I", version)
        cipher = Cipher(algorithms.AES(key), modes.GCM(nonce, tag))
        decryptor = cipher.decryptor()
        decryptor.authenticate_additional_data(aad)

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        temp_dst = dst_path.parent / f".tmp_{dst_path.name}_{uuid.uuid4().hex}"
        try:
            fd = os.open(temp_dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f_out:
                bytes_left = ct_total
                while bytes_left > 0:
                    read_len = min(CHUNK_SIZE, bytes_left)
                    chunk = f_in.read(read_len)
                    if len(chunk) != read_len:
                        raise BackupCryptoError("truncated backup ciphertext")
                    bytes_left -= len(chunk)
                    pt_chunk = decryptor.update(chunk)
                    if pt_chunk:
                        f_out.write(pt_chunk)
                final_pt = decryptor.finalize()
                if final_pt:
                    f_out.write(final_pt)
                f_out.flush()
                os.fsync(f_out.fileno())

            os.replace(temp_dst, dst_path)
            try:
                os.chmod(dst_path, 0o600)
            except OSError:
                pass
            return version
        except InvalidTag as exc:
            raise BackupCryptoError(
                f"backup decryption failed: tag verification failed (data corrupted or tampered): {exc}"
            ) from exc
        finally:
            if temp_dst.exists():
                try:
                    temp_dst.unlink()
                except OSError:
                    pass
