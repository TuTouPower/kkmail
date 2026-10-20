import os
import sys
import tempfile


ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Isolate every test run from real data. This runs before any test module imports
# web_outlook_app, so the app never opens ./data/outlook_accounts.db. Set
# KKMAIL_TEST_DATABASE_PATH to pin a specific throwaway DB when debugging.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="kkmail-tests-")
os.environ["DATABASE_PATH"] = os.environ.get(
    "KKMAIL_TEST_DATABASE_PATH", os.path.join(_TEST_DB_DIR, "test.db")
)
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("LOGIN_PASSWORD", "admin123")


import pytest  # noqa: E402


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
