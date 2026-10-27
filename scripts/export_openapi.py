#!/usr/bin/env python3
"""Dump mail-core OpenAPI schema to schemas/openapi.json (no HTTP server required).

Usage:
  python scripts/export_openapi.py
  python scripts/export_openapi.py --check   # exit 1 if committed file drifts

Frontend then regenerates TS with:
  (cd src/frontend && npm run openapi:gen)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "schemas" / "openapi.json"


def _ensure_minimal_env() -> None:
    """Importing the app must not require a live DB; fill placeholders if unset.

    Values are one-time random per process (A226): never embed a constant
    key — a published blob key / labelled placeholder could be mistaken
    for, or reused as, real key material. The schema dump never uses
    these values for real crypto.
    """
    os.environ.setdefault("MAIL_CORE_SECRET_KEY", secrets.token_hex(32))
    os.environ.setdefault(
        "MAIL_CORE_BLOB_KEY_V1", base64.b64encode(os.urandom(32)).decode("ascii")
    )
    os.environ.setdefault("MAIL_CORE_BLOB_ACTIVE_VERSION", "1")


def dump_schema() -> dict:
    _ensure_minimal_env()
    src = ROOT / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from mail_core.api.app import app

    return app.openapi()


def canonical(schema: dict) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare live app.openapi() to schemas/openapi.json without writing.",
    )
    args = parser.parse_args()
    schema = dump_schema()
    text = canonical(schema)

    if args.check:
        if not OUT.is_file():
            print(f"missing {OUT}; run without --check to create it", file=sys.stderr)
            return 1
        committed = OUT.read_text(encoding="utf-8")
        if committed != text:
            print(
                f"schemas/openapi.json is out of date with mail_core.api.app:app.openapi()\n"
                f"  run: python scripts/export_openapi.py && (cd src/frontend && npm run openapi:gen)",
                file=sys.stderr,
            )
            return 1
        print(f"ok: {OUT} matches live OpenAPI ({len(schema.get('paths', {}))} paths)")
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(schema.get('paths', {}))} paths, {len(schema.get('components', {}).get('schemas', {}))} schemas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
