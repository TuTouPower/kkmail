"""Application-layer attachment access."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from mail_core.blobs.access import (
    AttachmentAccessError,
    AttachmentPayload,
    PathTraversalRejected,
    parse_attachment_id,
    resolve_attachment_bytes,
)
from mail_core.blobs.archive import blob_root
from mail_core.blobs.store import BlobStore


def load_attachment(session: Session, attachment_id: str, *, root: Path | None = None) -> AttachmentPayload:
    aid = parse_attachment_id(attachment_id)
    store = BlobStore(root or blob_root())
    return resolve_attachment_bytes(session, aid, store=store)


__all__ = [
    "AttachmentAccessError",
    "AttachmentPayload",
    "PathTraversalRejected",
    "UUID",
    "load_attachment",
    "parse_attachment_id",
]
