"""A365: the OAuth callback page must not rely on CSP 'unsafe-inline'.

Its inline <style>/<script> blocks are authorized by a per-response
nonce instead, and the provider-controlled message stays HTML-escaped.
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

import mail_core.api.oauth_routes as routes
from mail_core.api.app import app


def test_callback_csp_uses_nonce_instead_of_unsafe_inline(monkeypatch):
    monkeypatch.setattr(
        routes,
        "complete_oauth_callback",
        lambda *_args, **_kwargs: (True, 200, "授权完成 <b>not-bold</b>"),
    )
    response = TestClient(app).get("/api/accounts/oauth/callback/microsoft?state=s&code=c")
    assert response.status_code == 200
    csp = response.headers["Content-Security-Policy"]
    assert "'unsafe-inline'" not in csp
    script_nonce = re.search(r"script-src 'nonce-([^']+)'", csp)
    style_nonce = re.search(r"style-src 'nonce-([^']+)'", csp)
    assert script_nonce and style_nonce
    assert script_nonce.group(1) == style_nonce.group(1)
    nonce = script_nonce.group(1)
    assert f'<style nonce="{nonce}">' in response.text
    assert f'<script nonce="{nonce}">' in response.text
    # The message is still escaped, never raw markup.
    assert "&lt;b&gt;not-bold&lt;/b&gt;" in response.text
    assert "<b>not-bold</b>" not in response.text


def test_callback_nonce_is_fresh_per_response(monkeypatch):
    monkeypatch.setattr(
        routes,
        "complete_oauth_callback",
        lambda *_args, **_kwargs: (False, 400, "失败"),
    )
    client = TestClient(app)
    nonces = set()
    for _ in range(3):
        csp = client.get("/api/accounts/oauth/callback/microsoft").headers[
            "Content-Security-Policy"
        ]
        match = re.search(r"script-src 'nonce-([^']+)'", csp)
        assert match
        nonces.add(match.group(1))
    assert len(nonces) == 3
