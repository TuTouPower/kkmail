"""OpenAPI schema must stay committed and match the live FastAPI app.

Local gate (no GitHub Actions): run this test after changing response_model / routes.
Then regenerate frontend types: `scripts/gen-openapi.sh` or `cd frontend && npm run openapi:gen`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
OPENAPI_PATH = ROOT / "docs" / "openapi.json"


def _canonical(schema: dict) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


@pytest.fixture(scope="module", autouse=True)
def _minimal_env_for_openapi():
    os.environ.setdefault("MAIL_CORE_SECRET_KEY", "openapi-test-placeholder-" + ("x" * 32))
    os.environ.setdefault("MAIL_CORE_BLOB_KEY_V1", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")
    os.environ.setdefault("MAIL_CORE_BLOB_ACTIVE_VERSION", "1")


def test_committed_openapi_json_matches_app():
    from mail_core.api.app import app

    live = app.openapi()
    assert OPENAPI_PATH.is_file(), f"missing {OPENAPI_PATH}; run scripts/export_openapi.py"
    committed = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    assert _canonical(live) == _canonical(committed), (
        "docs/openapi.json drifted from mail_core.api.app:app.openapi(); "
        "run: python scripts/export_openapi.py && cd frontend && npm run openapi:gen"
    )


def test_export_openapi_check_cli_passes():
    """Same check via the export script --check (what developers run by hand)."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_openapi.py"), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_openapi_documents_core_mail_and_account_routes():
    schema = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    paths = schema["paths"]
    for path in (
        "/api/mail/inbox",
        "/api/mail/search",
        "/api/mail/messages/{message_id}",
        "/api/accounts",
        "/api/groups",
        "/api/auth/login",
        "/health",
    ):
        assert path in paths, f"expected path {path} in OpenAPI"
    schemas = schema["components"]["schemas"]
    for name in ("MessageOut", "PageOut", "MessageDetailOut", "AccountOut", "MutationOut"):
        assert name in schemas, f"expected schema {name}"
