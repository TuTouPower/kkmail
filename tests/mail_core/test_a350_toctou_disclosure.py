"""A350: the IMAP host validation has a known DNS TOCTOU window (build-time
resolution vs connect-time re-resolution; the peer re-check runs only after
TCP/TLS is established). The accepted residual risk must be explicitly
documented in host_security, as the adoption fix prescribes."""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "mail_core" / "providers"


def test_host_security_documents_toctou_residual_risk():
    text = (SRC / "host_security.py").read_text(encoding="utf-8")
    assert "TOCTOU" in text
    assert "rebinding" in text.lower()
    # The disclosure must state what still protects credentials: the peer
    # check runs before login, so credentials are never sent to a
    # restricted peer even though the connection itself may be established.
    assert "before" in text and "login" in text


def test_factory_validation_references_the_window():
    text = (SRC / "factory.py").read_text(encoding="utf-8")
    assert "TOCTOU" in text
