#!/usr/bin/env python3
"""Verify or regenerate production dependency lockfile consistency."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TXT_FILE = ROOT / "requirements-mail-core.txt"
LOCK_FILE = ROOT / "requirements-mail-core.lock"


def run_compile(output_path: Path) -> int:
    cmd = [
        "uv",
        "pip",
        "compile",
        str(TXT_FILE),
        "--universal",
        "--python-version",
        "3.13",
        "--generate-hashes",
        "-o",
        str(output_path),
    ]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"Error compiling lockfile with uv:\n{proc.stderr}", file=sys.stderr)
    return proc.returncode


def strip_header_comments(text: str) -> str:
    lines = text.splitlines()
    return "\n".join(line for line in lines if not line.startswith("#"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check or update requirements-mail-core.lock")
    parser.add_argument("--check", action="store_true", help="Check lockfile is up-to-date without writing")
    args = parser.parse_args()

    if not TXT_FILE.is_file():
        print(f"Missing {TXT_FILE}", file=sys.stderr)
        return 1

    if not args.check:
        print(f"Compiling {LOCK_FILE.name} from {TXT_FILE.name}...")
        rc = run_compile(LOCK_FILE)
        if rc == 0:
            print(f"Successfully generated {LOCK_FILE}")
        return rc

    if not LOCK_FILE.is_file():
        print(f"Lockfile {LOCK_FILE} does not exist. Run scripts/check_dep_locks.py to generate it.", file=sys.stderr)
        return 1

    with tempfile.NamedTemporaryFile("w+", suffix=".lock", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        rc = run_compile(tmp_path)
        if rc != 0:
            return rc

        current_content = strip_header_comments(LOCK_FILE.read_text(encoding="utf-8"))
        fresh_content = strip_header_comments(tmp_path.read_text(encoding="utf-8"))

        if current_content != fresh_content:
            print(
                f"ERROR: {LOCK_FILE.name} is out of date with {TXT_FILE.name}!\n"
                f"Run: python scripts/check_dep_locks.py to regenerate it.",
                file=sys.stderr,
            )
            return 1

        print(f"OK: {LOCK_FILE.name} is synchronized with {TXT_FILE.name}")
        return 0
    finally:
        tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
