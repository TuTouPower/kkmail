"""A226: export_openapi.py must not embed usable constant keys as env defaults.

The OpenAPI dump only needs *some* syntactically valid key material so the
app can be imported without a live DB. Those values must be one-time random
per process, never a published constant (the all-zero blob key / a labelled
placeholder) that a reader could mistake for — or reuse as — a real key.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "export_openapi.py"

_KEYS = ("MAIL_CORE_SECRET_KEY", "MAIL_CORE_BLOB_KEY_V1")

_PROBE = """
import importlib.util
import json
import os
import sys

for key in ("MAIL_CORE_SECRET_KEY", "MAIL_CORE_BLOB_KEY_V1", "MAIL_CORE_BLOB_ACTIVE_VERSION"):
    os.environ.pop(key, None)
spec = importlib.util.spec_from_file_location("export_openapi", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod._ensure_minimal_env()
print(json.dumps({key: os.environ.get(key) for key in ("MAIL_CORE_SECRET_KEY", "MAIL_CORE_BLOB_KEY_V1")}))
"""


def _generated_env() -> dict:
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE, str(SCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_export_openapi_source_has_no_constant_key_material():
    text = SCRIPT.read_text(encoding="utf-8")
    assert "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=" not in text
    assert "openapi-export-placeholder" not in text


def test_export_openapi_generates_one_time_random_keys():
    first = _generated_env()
    second = _generated_env()
    for key in _KEYS:
        assert first[key], f"{key} must be filled when unset"
        assert first[key] != second[key], f"{key} must be random per process, not a constant"
    blob = base64.b64decode(first["MAIL_CORE_BLOB_KEY_V1"], validate=True)
    assert len(blob) == 32
    assert blob != bytes(32)
