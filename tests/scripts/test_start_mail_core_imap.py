from __future__ import annotations

import os
import socket
import subprocess
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
