from io import BytesIO
from types import SimpleNamespace

import pytest

import mail_core.api.mail as mail_api


@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        ("application/pdf", "application/pdf"),
        ("application/vnd.example+json", "application/vnd.example+json"),
        ("text/plain; charset=utf-8", "application/octet-stream"),
        ("text/plain\r\nX-Evil: yes", "application/octet-stream"),
        ("not-a-media-type", "application/octet-stream"),
        (None, "application/octet-stream"),
    ],
)
def test_attachment_response_validates_content_type(monkeypatch, content_type, expected):
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    payload = SimpleNamespace(
        filename="attachment.bin",
        content_sha256="a" * 64,
        size_bytes=0,
        content_type=content_type,
        open_stream=lambda: BytesIO(b""),
    )
    monkeypatch.setattr(mail_api, "get_session_factory", lambda: Session)
    monkeypatch.setattr(mail_api, "load_attachment", lambda *_args: payload)

    response = mail_api.api_get_attachment("attachment-id")

    assert response.headers["content-type"] == expected
    assert response.headers["x-content-type-options"] == "nosniff"
