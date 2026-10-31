"""Tests for remote image allowlists and inline preview endpoints (t066)."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from mail_core.api.app import app
from mail_core.db.session import get_session_factory
from mail_core.mail.storage.models import (
    Account,
    Attachment,
    Message,
    MessageBlob,
    MessageBody,
)
from mail_core.security.inline_preview import sign_inline_image_preview_token
from tests.mail_core.conftest import TEST_API_KEY


_db_required = pytest.mark.skipif(
    not os.environ.get("MAIL_CORE_DATABASE_URL"),
    reason="MAIL_CORE_DATABASE_URL not set",
)


@_db_required
def test_allow_remote_images_endpoints(monkeypatch):
    monkeypatch.setenv("MAIL_CORE_SECRET_KEY", "test-secret-key-for-api-t066-random")
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {TEST_API_KEY}"}

    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            email=f"sender-test-{uuid.uuid4().hex[:8]}@example.com",
            provider="stub",
            credential_ref="cred_ref",
        )
        session.add(acc)
        session.flush()

        msg = Message(
            account_id=acc.id,
            remote_id=f"r-{uuid.uuid4().hex[:8]}",
            subject="API Allow Test",
            from_address="newsletter@verified-sender.org",
            from_name="News Letter",
            to_addresses=["me@example.com"],
            cc_addresses=[],
            sort_time=datetime.now(timezone.utc),
            is_read=False,
            is_flagged=False,
            has_attachments=False,
            snippet="",
        )
        session.add(msg)
        session.commit()
        msg_id = msg.id

    # 1. Message detail initially reports remote_images_allowed = False
    res = client.get(f"/api/mail/messages/{msg_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["remote_images_allowed"] is False
    assert res.json()["can_allow_sender"] is True

    # 2. Allow single message
    res = client.post(f"/api/mail/messages/{msg_id}/allow-remote-images", headers=headers)
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["remote_images_allowed"] is True

    # Detail now reports remote_images_allowed = True
    res = client.get(f"/api/mail/messages/{msg_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["remote_images_allowed"] is True

    # 3. Allow sender via message UUID (server extracts structured from_address)
    res = client.post(
        "/api/mail/senders/allow-remote-images",
        json={"message_id": str(msg_id)},
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["success"] is True

    # List allowed senders
    res = client.get("/api/mail/senders/allowed-remote-images", headers=headers)
    assert res.status_code == 200
    senders = res.json()
    assert any(s["from_address"] == "newsletter@verified-sender.org" for s in senders)
    sender_entry = next(s for s in senders if s["from_address"] == "newsletter@verified-sender.org")

    # 4. Remove allowed sender
    res = client.delete(f"/api/mail/senders/allowed-remote-images/{sender_entry['id']}", headers=headers)
    assert res.status_code == 200

    res = client.get("/api/mail/senders/allowed-remote-images", headers=headers)
    assert not any(s["from_address"] == "newsletter@verified-sender.org" for s in res.json())


@_db_required
def test_inline_attachment_preview_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("MAIL_CORE_SECRET_KEY", "test-secret-key-for-preview-t066-random")
    client = TestClient(app)

    # Note: no auth header passed to preview endpoint to verify sandbox compatibility!
    Session = get_session_factory()
    with Session() as session:
        acc = Account(
            email=f"preview-acc-{uuid.uuid4().hex[:8]}@test.local",
            provider="stub",
            credential_ref="cred_ref",
        )
        session.add(acc)
        session.flush()

        msg = Message(
            account_id=acc.id,
            remote_id=f"r-{uuid.uuid4().hex[:8]}",
            subject="Inline Preview Test",
            from_address="sender@test.local",
            to_addresses=["me@test.local"],
            sort_time=datetime.now(timezone.utc),
        )
        session.add(msg)
        session.flush()
        msg_id = msg.id

        # Seed an inline attachment
        att = Attachment(
            message_id=msg_id,
            filename="logo.png",
            content_type="image/png",
            size_bytes=4,
            content_id="logo_cid@test",
            is_inline=True,
        )
        session.add(att)
        session.commit()
        att_id = str(att.id)

    valid_token = sign_inline_image_preview_token(att_id)

    # 1. Without token -> 422 (FastAPI required query param)
    res = client.get(f"/api/mail/attachments/{att_id}/preview")
    assert res.status_code == 422

    # 2. Tampered token -> 401
    res = client.get(f"/api/mail/attachments/{att_id}/preview?token=invalid_token")
    assert res.status_code == 401

    # 3. Nonexistent attachment -> 404 (with valid signature for random UUID)
    random_id = str(uuid.uuid4())
    random_token = sign_inline_image_preview_token(random_id)
    res = client.get(f"/api/mail/attachments/{random_id}/preview?token={random_token}")
    assert res.status_code == 404

    # 4. HEAD request supported with same auth
    res_head = client.head(f"/api/mail/attachments/{att_id}/preview?token=invalid")
    assert res_head.status_code == 401

    # 5. Non-inline attachment -> 403
    with Session() as session:
        non_inline = Attachment(
            message_id=msg_id,
            filename="doc.pdf",
            content_type="application/pdf",
            size_bytes=10,
            is_inline=False,
        )
        session.add(non_inline)
        session.commit()
        non_inline_id = str(non_inline.id)

    tok_non_inline = sign_inline_image_preview_token(non_inline_id)
    res = client.get(f"/api/mail/attachments/{non_inline_id}/preview?token={tok_non_inline}")
    assert res.status_code == 403

    # 6. SVG attachment -> 403
    with Session() as session:
        svg_att = Attachment(
            message_id=msg_id,
            filename="vector.svg",
            content_type="image/svg+xml",
            size_bytes=20,
            is_inline=True,
        )
        session.add(svg_att)
        session.commit()
        svg_id = str(svg_att.id)

    tok_svg = sign_inline_image_preview_token(svg_id)
    res = client.get(f"/api/mail/attachments/{svg_id}/preview?token={tok_svg}")
    assert res.status_code == 403


@_db_required
def test_allow_endpoints_auth_and_errors():
    client = TestClient(app)
    fake_id = uuid.uuid4()

    # Without auth -> 401
    res = client.post(f"/api/mail/messages/{fake_id}/allow-remote-images")
    assert res.status_code == 401

    res = client.post("/api/mail/senders/allow-remote-images", json={"message_id": str(fake_id)})
    assert res.status_code == 401

    # With auth but nonexistent IDs -> 404
    headers = {"Authorization": f"Bearer {TEST_API_KEY}"}
    res = client.post(f"/api/mail/messages/{fake_id}/allow-remote-images", headers=headers)
    assert res.status_code == 404

    res = client.post("/api/mail/senders/allow-remote-images", json={"message_id": str(fake_id)}, headers=headers)
    assert res.status_code == 404

    res = client.delete(f"/api/mail/senders/allowed-remote-images/{fake_id}", headers=headers)
    assert res.status_code == 404


def test_log_token_redaction():
    from mail_core.security.redact import redact

    sample_url = "/api/mail/attachments/123/preview?token=sensitive-hmac-token-secret&other=val"
    redacted = redact(sample_url)
    assert "token=[REDACTED]" in redacted
    assert "sensitive-hmac-token-secret" not in redacted
