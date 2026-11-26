"""Root pytest config covering tests/mail_core and tests/scripts."""

import os
import sys

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)


@pytest.fixture(autouse=True)
def _isolate_outbound_network_state(monkeypatch):
    """Keep hermetic tests isolated from shell proxy/timeout vars and bulkhead/config singletons."""
    from mail_core.config import reset_config
    from mail_core.net.bulkhead import configure_default_bulkhead, default_bulkhead

    for key in (
        "HTTP_PROXY",
        "http_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "ALL_PROXY",
        "all_proxy",
        "NO_PROXY",
        "no_proxy",
        "MAIL_CORE_OUTBOUND_PROXY",
        "MAIL_CORE_NO_PROXY",
        "MAIL_CORE_CONNECT_TIMEOUT_S",
        "MAIL_CORE_CONNECT_ATTEMPT_TIMEOUT_S",
        "MAIL_CORE_CIRCUIT_FAILURE_THRESHOLD",
        "MAIL_CORE_CIRCUIT_COOLDOWN_S",
        "MAIL_CORE_PROXY_ALLOW_CIDRS",
    ):
        monkeypatch.delenv(key, raising=False)
    default_bulkhead().reset()
    configure_default_bulkhead(failure_threshold=2, cooldown_s=30.0)
    reset_config()
    yield
    default_bulkhead().reset()
    configure_default_bulkhead(failure_threshold=2, cooldown_s=30.0)
    reset_config()


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
