"""Root pytest config. All tests live under tests/mail_core/."""

import os
import sys

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


@pytest.fixture
def fake_frontend_dist(tmp_path, monkeypatch):
    """A minimal Vite-like build so SPA tests do not need `npm run build`."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(
        '<!doctype html><html><body><div id="root"></div>'
        '<script type="module" src="/assets/app-test.js"></script></body></html>',
        encoding="utf-8",
    )
    (dist / "assets" / "app-test.js").write_text("console.log('kkmail')", encoding="utf-8")
    monkeypatch.setenv("KKMAIL_FRONTEND_DIST", str(dist))
    return dist
