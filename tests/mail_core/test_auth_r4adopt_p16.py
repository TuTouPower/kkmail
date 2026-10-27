"""R4 adoption P16: auth hardening regressions (A87/A88/A119/A188/A250/A251/A324)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mail_core.security.auth import reset_auth_caches

_AUTH_PY = Path(__file__).resolve().parent.parent.parent / "src" / "mail_core" / "security" / "auth.py"


@pytest.fixture(autouse=True)
def _reset_auth():
    reset_auth_caches()
    yield
    reset_auth_caches()


def test_a188_session_epoch_declared_once():
    source = _AUTH_PY.read_text(encoding="utf-8")
    declarations = re.findall(r"^_session_epoch: int = 1$", source, flags=re.MULTILINE)
    assert len(declarations) == 1
