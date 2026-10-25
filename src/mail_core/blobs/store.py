"""Content-addressed encrypted blob store (architecture §10.2)."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from collections.abc import Iterator

from mail_core.blobs.crypto import BlobIntegrityError, Keyring, iter_unwrap, load_keyring_from_env, read_key_version, wrap

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class InvalidBlobDigest(ValueError):
    """Digest is not a 64-char lowercase hex SHA-256."""


@dataclass(frozen=True, slots=True)
class BlobWriteResult:
    content_sha256: str
    size_bytes: int
    storage_path: str
    key_version: int


class BlobStore:
    """Filesystem layout: {root}/{ab}/{cd}/{sha256}.blob

    Writes are atomic (temp file + rename). Plaintext SHA-256 addresses the
    object; on-disk bytes are AES-GCM wrapped with a versioned key.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        key_version: int | None = None,
        keyring: Keyring | None = None,
    ) -> None:
        self.root = Path(root)
        self.keyring = keyring or load_keyring_from_env()
        self.key_version = key_version if key_version is not None else self.keyring.active_version
        self.root.mkdir(parents=True, exist_ok=True)

    def hash_plaintext(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _normalize_digest(self, digest: str) -> str:
        d = (digest or "").lower().strip()
        if not _HEX64.match(d):
            raise InvalidBlobDigest("content digest must be 64 hex chars")
        return d

    def _rel_path(self, digest: str) -> str:
        digest = self._normalize_digest(digest)
        return f"{digest[:2]}/{digest[2:4]}/{digest}.blob"

    def path_for(self, digest: str) -> Path:
        rel = self._rel_path(digest)
        full = (self.root / rel).resolve()
        root = self.root.resolve()
        if root not in full.parents:
            raise InvalidBlobDigest("resolved path escapes blob root")
        return full

    def exists(self, digest: str) -> bool:
        return self.path_for(digest).is_file()

    def put(self, data: bytes) -> BlobWriteResult:
        digest = self.hash_plaintext(data)
        rel = self._rel_path(digest)
        dest = self.root / rel
        if dest.is_file():
            try:
                with dest.open("rb") as fh:
                    disk_version = read_key_version(fh)
                    fh.seek(0)
                    h = hashlib.sha256()
                    for chunk in iter_unwrap(fh, keyring=self.keyring):
                        h.update(chunk)
                    if h.hexdigest() != digest:
                        raise BlobIntegrityError("existing blob hash mismatch")
                disk_size = dest.stat().st_size
                return BlobWriteResult(digest, disk_size, rel, disk_version)
            except BlobIntegrityError:
                pass
        dest.parent.mkdir(parents=True, exist_ok=True)
        payload = wrap(data, keyring=self.keyring, key_version=self.key_version)
        fd, tmp_name = tempfile.mkstemp(dir=dest.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_name, dest)
        except Exception:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return BlobWriteResult(digest, len(payload), rel, self.key_version)

    def get(self, digest: str) -> bytes:
        """Assemble plaintext via streaming decrypt (same path as attachment download)."""
        return b"".join(self.iter_plaintext(digest))

    def get_with_version(self, digest: str) -> tuple[bytes, int]:
        digest = self._normalize_digest(digest)
        with self.path_for(digest).open("rb") as fh:
            version = read_key_version(fh)
        plaintext = b"".join(self.iter_plaintext(digest))
        return plaintext, version

    def iter_plaintext(self, digest: str) -> Iterator[bytes]:
        """Stream-decrypt one chunk at a time; verifies the SHA-256 at the end.

        AES-GCM authenticates every frame, and the final-frame flag rejects
        truncation, so only authenticated bytes are ever yielded.
        """
        digest = self._normalize_digest(digest)
        path = self.path_for(digest)
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter_unwrap(fh, keyring=self.keyring):
                h.update(chunk)
                yield chunk
        if h.hexdigest() != digest:
            raise BlobIntegrityError("blob content does not match its digest")
