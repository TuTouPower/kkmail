"""Attachment / blob access helpers (architecture §10.2 / M5).

API must accept only attachment UUIDs — never filesystem path parameters.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from mail_core.blobs.store import BlobStore, InvalidBlobDigest
from mail_core.mail.storage.models import Attachment, MessageBlob

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class AttachmentAccessError(LookupError):
    """Attachment missing or not yet archived."""


class PathTraversalRejected(ValueError):
    """Caller tried to pass a filesystem path instead of an attachment id."""


def assert_not_path_param(value: str) -> None:
    """Reject obvious path-shaped inputs before they touch the disk."""
    if not value or value.strip() != value:
        raise PathTraversalRejected("empty or padded attachment id")
    if any(ch in value for ch in ("/", "\\", "..", "\0")):
        raise PathTraversalRejected("path-shaped attachment id rejected")
    if value.startswith(".") or ":" in value:
        raise PathTraversalRejected("path-shaped attachment id rejected")


def parse_attachment_id(raw: str) -> uuid.UUID:
    assert_not_path_param(raw)
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise PathTraversalRejected("attachment id must be a UUID") from exc


def validate_content_digest(digest: str) -> str:
    d = (digest or "").lower().strip()
    if not _HEX64.match(d):
        raise InvalidBlobDigest("content digest must be 64 hex chars")
    return d


@dataclass(frozen=True, slots=True)
class AttachmentPayload:
    attachment_id: uuid.UUID
    message_id: uuid.UUID
    filename: str
    content_type: str | None
    size_bytes: int | None
    content_sha256: str
    open_stream: Callable[[], Iterator[bytes]]


def resolve_attachment_bytes(
    session: Session,
    attachment_id: uuid.UUID,
    *,
    store: BlobStore,
) -> AttachmentPayload:
    """Load attachment bytes by UUID only (architecture: no path params)."""
    att = session.get(Attachment, attachment_id)
    if att is None:
        raise AttachmentAccessError("attachment not found")
    if att.blob_id is None:
        raise AttachmentAccessError("attachment blob not archived yet")
    blob = session.get(MessageBlob, att.blob_id)
    if blob is None:
        raise AttachmentAccessError("blob record missing")
    try:
        digest = validate_content_digest(blob.content_sha256)
    except InvalidBlobDigest as exc:
        raise AttachmentAccessError("attachment blob is unavailable") from exc
    # Never use storage_path from DB as a user-controlled path; re-derive from digest.
    path = store.path_for(digest)
    if not path.is_file():
        raise AttachmentAccessError("attachment blob missing on disk")
    return AttachmentPayload(
        attachment_id=att.id,
        message_id=att.message_id,
        filename=att.filename,
        content_type=att.content_type,
        size_bytes=att.size_bytes,
        content_sha256=digest,
        # A81: downloads must not stream plaintext before its digest is
        # verified — use the verify-first stream, not iter_plaintext.
        open_stream=lambda: store.iter_plaintext_verified(digest),
    )


def safe_blob_path(root: Path, digest: str) -> Path:
    """Resolve on-disk path under root; reject traversal."""
    digest = validate_content_digest(digest)
    rel = Path(digest[:2]) / digest[2:4] / f"{digest}.blob"
    full = (root / rel).resolve()
    root_resolved = root.resolve()
    if root_resolved not in full.parents:
        raise PathTraversalRejected("resolved path escapes blob root")
    return full
