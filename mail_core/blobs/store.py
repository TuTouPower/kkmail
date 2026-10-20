"""Content-addressed blob store stubs (architecture §10.2).

Plaintext SHA-256 addresses objects; ciphertext is written under an
application-layer encryption wrapper (key_version). Real crypto lands later.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BlobWriteResult:
    content_sha256: str
    size_bytes: int
    storage_path: str
    key_version: int


class BlobStore:
    """Filesystem layout: {root}/{ab}/{cd}/{sha256}.blob

    Writes are atomic (temp file + rename). Encryption is a stub that currently
    stores plaintext with key_version=0 so tests can exercise the path.
    """

    def __init__(self, root: str | Path, *, key_version: int = 0) -> None:
        self.root = Path(root)
        self.key_version = key_version
        self.root.mkdir(parents=True, exist_ok=True)

    def hash_plaintext(self, data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def _rel_path(self, digest: str) -> str:
        return f"{digest[:2]}/{digest[2:4]}/{digest}.blob"

    def path_for(self, digest: str) -> Path:
        return self.root / self._rel_path(digest)

    def exists(self, digest: str) -> bool:
        return self.path_for(digest).is_file()

    def put(self, data: bytes) -> BlobWriteResult:
        digest = self.hash_plaintext(data)
        rel = self._rel_path(digest)
        dest = self.root / rel
        if dest.is_file():
            return BlobWriteResult(digest, len(data), rel, self.key_version)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Stub "encryption": identity transform; real AES-GCM comes later.
        payload = self._wrap(data)
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
        return BlobWriteResult(digest, len(data), rel, self.key_version)

    def get(self, digest: str) -> bytes:
        raw = self.path_for(digest).read_bytes()
        return self._unwrap(raw)

    def _wrap(self, plaintext: bytes) -> bytes:
        return plaintext

    def _unwrap(self, ciphertext: bytes) -> bytes:
        return ciphertext
