import os
import sys
import tempfile

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Isolate any residual SQLite paths (legacy).
_TEST_DB_DIR = tempfile.mkdtemp(prefix="kkmail-tests-")
os.environ["DATABASE_PATH"] = os.environ.get(
    "KKMAIL_TEST_DATABASE_PATH", os.path.join(_TEST_DB_DIR, "test.db")
)
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("LOGIN_PASSWORD", "test-login-password")


import pytest  # noqa: E402


def pytest_ignore_collect(collection_path, path=None):  # path= for older pytest
    """Flask backend removed — do not collect legacy root tests."""
    p = str(collection_path)
    norm = p.replace("\\", "/")
    if "/tests/mail_core/" in norm:
        return False
    if norm.rstrip("/").endswith("/tests") or norm.rstrip("/").endswith("/tests/conftest.py"):
        return False
    if "/tests/" in norm and norm.endswith(".py"):
        # Skip all non-mail_core tests under tests/
        if "/tests/mail_core/" not in norm:
            return True
    return None


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
