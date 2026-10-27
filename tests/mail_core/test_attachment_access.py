"""M5: attachment access by UUID only; reject path traversal."""

from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from mail_core.api.app import app
from tests.mail_core.conftest import TEST_API_KEY
from mail_core.blobs.access import (
    AttachmentAccessError,
    PathTraversalRejected,
    assert_not_path_param,
    parse_attachment_id,
    resolve_attachment_bytes,
    validate_content_digest,
)
from mail_core.blobs.store import BlobStore, InvalidBlobDigest
from mail_core.mail.storage.models import Attachment, MessageBlob
from mail_core.security.defaults import REMOTE_IMAGES_DEFAULT_ON, require_encrypted_volume_docs


def test_remote_images_default_off():
    assert REMOTE_IMAGES_DEFAULT_ON is False
    assert "encrypted" in require_encrypted_volume_docs().lower()


@pytest.mark.parametrize(
    "bad",
    [
        "../etc/passwd",
        "..\\windows\\system32",
        "/var/lib/blobs/ab/cd/x.blob",
        "ab/cd/deadbeef.blob",
        "./secret",
        "C:\\Users\\x",
        "",
        "  spaced  ",
    ],
)
def test_reject_path_params(bad):
    with pytest.raises(PathTraversalRejected):
        assert_not_path_param(bad)


def test_parse_uuid_ok():
    u = uuid.uuid4()
    assert parse_attachment_id(str(u)) == u


def test_parse_non_uuid_rejected():
    with pytest.raises(PathTraversalRejected):
        parse_attachment_id("not-a-uuid")


def test_digest_validation(tmp_path):
    good = "a" * 64
    assert validate_content_digest(good) == good
    with pytest.raises(InvalidBlobDigest):
        validate_content_digest("../" + "a" * 60)
    with pytest.raises(InvalidBlobDigest):
        validate_content_digest("zz" * 32)
    store = BlobStore(tmp_path)
    with pytest.raises(InvalidBlobDigest):
        store.path_for("../" + "b" * 62)
    with pytest.raises(InvalidBlobDigest):
        store.get("not-hex")


def test_attachment_with_invalid_blob_digest_is_unavailable_not_unhandled(tmp_path):
    attachment_id = uuid.uuid4()
    blob_id = uuid.uuid4()
    rows = {
        (Attachment, attachment_id): SimpleNamespace(blob_id=blob_id),
        (MessageBlob, blob_id): SimpleNamespace(content_sha256="not-a-valid-digest"),
    }

    class Session:
        def get(self, model, row_id):
            return rows.get((model, row_id))

    with pytest.raises(AttachmentAccessError, match="attachment blob is unavailable"):
        resolve_attachment_bytes(Session(), attachment_id, store=BlobStore(tmp_path))


def test_safe_blob_path_removed():
    # A217: safe_blob_path had no production caller (attachment resolution
    # already derives paths via BlobStore.path_for) and merely duplicated
    # path_for's traversal guard. It is deleted rather than kept as a
    # second implementation; this replaces its old behaviour test.
    import mail_core.blobs.access as access

    assert not hasattr(access, "safe_blob_path")


def test_api_rejects_path_shaped_attachment_id():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    r = client.get("/api/mail/attachments/../etc/passwd")
    # Starlette may normalize path; either 400 from our handler or 404 from router.
    assert r.status_code in (400, 404)


def test_api_rejects_by_path_route():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    r = client.get("/api/mail/attachments/by-path/var/lib/blobs/x.blob")
    assert r.status_code == 400
    assert "path" in r.json()["detail"].lower()


DATABASE_URL = os.environ.get("MAIL_CORE_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="database required")
def test_api_unknown_uuid_404():
    client = TestClient(app, headers={"Authorization": f"Bearer {TEST_API_KEY}"})
    r = client.get(f"/api/mail/attachments/{uuid.uuid4()}")
    # An unknown attachment UUID is a clean 404 (AttachmentAccessError ->
    # HTTPException(404, "attachment not found")) — 500/503 would mean the
    # error path itself is broken and must not be tolerated here.
    assert r.status_code == 404
    assert r.json()["detail"] == "attachment not found"
