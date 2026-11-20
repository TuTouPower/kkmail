"""p082: pin_base_images must not bootstrap through a daemon-pulled container image."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "pin_base_images.sh"
LOCK = ROOT / "config" / "base_images.lock"
POLICY = ROOT / "config" / "containers" / "skopeo-policy.json"


def script_text() -> str:
    lines = [
        line for line in SCRIPT.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    return "\n".join(lines)


def lock_data() -> dict:
    return json.loads(LOCK.read_text(encoding="utf-8"))


def test_script_has_no_container_bootstrap():
    text = script_text()
    assert "docker run" not in text
    assert "alpine:latest" not in text


def test_script_uses_checksum_pinned_host_tool_into_daemon():
    text = script_text()
    assert "docker-daemon:" in text
    assert "--policy" in text
    assert "--override-os" in text
    assert "expected_sha" in text
    assert "KKMAIL_PIN_PROXY" in text


def test_lock_pins_skopeo_for_supported_hosts():
    tools = lock_data()["_tools"]["skopeo"]
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", tools["version"])
    assert "{os}" in tools["base_url"] and "{arch}" in tools["base_url"]
    checksums = tools["sha256"]
    assert {"darwin_arm64", "darwin_amd64", "linux_arm64", "linux_amd64"} <= set(checksums)
    for value in checksums.values():
        assert re.fullmatch(r"[0-9a-f]{64}", value)


def test_trust_policy_is_tracked():
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["default"] == [{"type": "insecureAcceptAnything"}]
