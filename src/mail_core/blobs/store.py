"""Content-addressed encrypted blob store (architecture §10.2)."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from collections.abc import Iterator

from mail_core.blobs.crypto import BlobCryptoError, BlobIntegrityError, Keyring, iter_unwrap, load_keyring_from_env, read_key_version, wrap

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _fsync_dir(path: Path) -> None:
    """fsync a directory so a rename inside it is durable (A138)."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


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
        # A138: per-digest put locks (registry guarded by its own lock).
        self._put_locks: dict[str, threading.Lock] = {}
        self._put_locks_guard = threading.Lock()

    def _lock_for_digest(self, digest: str) -> threading.Lock:
        with self._put_locks_guard:
            return self._put_locks.setdefault(digest, threading.Lock())

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
        # A138: serialise the verify-then-write sequence per digest so a
        # concurrent put of the same content cannot interleave with the
        # existence check / replacement below.
        with self._lock_for_digest(digest):
            return self._put_locked(data, digest)

    def _put_locked(self, data: bytes, digest: str) -> BlobWriteResult:
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
            except BlobCryptoError:
                # A138: catch the whole crypto error family, not only the
                # BlobIntegrityError subclass — an existing blob written
                # under an unknown key version raises plain
                # BlobCryptoError and must also fall through to a rewrite.
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
            _fsync_dir(dest.parent)
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

        AES-GCM authenticates each frame before yielding its chunk, but the
        content digest is checked only after the iterator is exhausted. Streaming
        callers must treat any terminal ``BlobCryptoError`` as a failed response
        and discard partial output. Use ``get()`` when verification must finish
        before plaintext is exposed to the caller.
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

    def iter_plaintext_verified(self, digest: str) -> Iterator[bytes]:
        """Yield plaintext only after the full digest check has passed (A81).

        Decrypted chunks are spooled to an anonymous temp file while
        ``iter_plaintext`` verifies the content SHA-256; nothing is
        yielded until that verification completes, so callers that send
        the chunks onward (attachment downloads) never emit unverified
        bytes. Memory stays bounded regardless of blob size.
        """
        spool = tempfile.TemporaryFile()
        try:
            for chunk in self.iter_plaintext(digest):
                spool.write(chunk)
            spool.seek(0)
            while True:
                chunk = spool.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            spool.close()
