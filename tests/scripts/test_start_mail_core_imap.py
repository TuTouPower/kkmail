from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "start-mail-core-imap.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_docker_success_waits_for_imap_tcp_readiness(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "docker", "#!/bin/sh\nsleep 0.1\nexit 0\n")

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    listener_started = threading.Event()

    def start_listener():
        time.sleep(0.7)
        server.listen()
        listener_started.set()

    listener = threading.Thread(target=start_listener, daemon=True)
    listener.start()
    env = os.environ.copy()
    env.update(
        PATH=f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
        MAIL_CORE_IMAP_HOST="127.0.0.1",
        MAIL_CORE_IMAP_PORT=str(port),
        KKMAIL_TEST_PG_PASSWORD="test-only",
    )
    started = time.monotonic()
    try:
        result = subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=5,
        )
    finally:
        server.close()

    assert result.returncode == 0, result.stderr
    assert "Dovecot IMAP via test compose" in result.stdout
    assert listener_started.is_set()
    assert time.monotonic() - started >= 0.6


def test_docker_errors_are_visible_when_no_fallback_is_available(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "docker", "#!/bin/sh\necho 'compose startup failure' >&2\nexit 1\n")
    _write_executable(fake_bin / "python3", "#!/bin/sh\nexit 1\n")

    env = os.environ.copy()
    env.update(
        PATH=f"{fake_bin}:/bin:/usr/bin",
        KKMAIL_TEST_PG_PASSWORD="test-only",
    )
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 1
    assert result.stderr.count("compose startup failure") == 2
    assert "Neither docker compose imap nor pymap is available" in result.stderr


def test_pymap_fallback_passes_private_passfile_and_cleans_it_up(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "docker", "#!/bin/sh\nexit 1\n")

    capture = tmp_path / "pymap_capture.json"
    stub = tmp_path / "pymap_stub.py"
    stub.write_text(
        """import json
import os
import pathlib
import stat
import sys

args = sys.argv[1:]
passfile = pathlib.Path(args[args.index('--passfile') + 1])
capture = pathlib.Path(os.environ['KKMAIL_PYMAP_CAPTURE'])
capture.write_text(json.dumps({
    'args': args,
    'passfile': str(passfile),
    'mode': stat.S_IMODE(passfile.stat().st_mode),
    'contents': passfile.read_text(),
}), encoding='utf-8')
""",
        encoding="utf-8",
    )
    fake_python = """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "-c" ]]; then exit 0; fi
if [[ "$1" == "-m" && "$2" == "pymap" ]]; then
  shift 2
  exec "$KKMAIL_REAL_PYTHON" "$KKMAIL_PYMAP_STUB" "$@"
fi
exit 1
"""
    _write_executable(fake_bin / "python3", fake_python)

    secret = "imap-secret-never-in-argv"
    env = os.environ.copy()
    env.update(
        PATH=f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
        KKMAIL_TEST_PG_PASSWORD="test-only",
        KKMAIL_PYMAP_CAPTURE=str(capture),
        KKMAIL_PYMAP_STUB=str(stub),
        KKMAIL_REAL_PYTHON=sys.executable,
        MAIL_CORE_IMAP_HOST="127.0.0.1",
        MAIL_CORE_IMAP_PORT="1143",
        MAIL_CORE_IMAP_USER="alice@kkmail.test",
        MAIL_CORE_IMAP_PASS=secret,
    )
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stderr
    assert "Starting pymap on :1143 (fallback)" in result.stdout
    data = json.loads(capture.read_text(encoding="utf-8"))
    assert "--passfile" in data["args"]
    assert secret not in data["args"]
    assert data["mode"] == 0o600
    assert data["contents"] == f"alice@kkmail.test {secret}\n"
    assert not Path(data["passfile"]).exists()
