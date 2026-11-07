"""Tests for doc sensitivity checker (scripts/check_doc_sensitive.py)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "check_doc_sensitive.py"


def run_checker(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SCRIPT), *args]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


def test_normal_document_passes(tmp_path: Path):
    doc = tmp_path / "normal_doc.md"
    doc.write_text(
        """# Sample Normal Spec

This document describes a feature.
- Contact: user@example.com, test@test.com, admin@example.org
- Documentation: rfc@ietf.org
- Paths: src/mail_core/engine.py, <workspace>/kkmail, /home/runner/work
- Status: done
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 0, f"Expected 0 but got {proc.returncode}: {proc.stderr}"
    assert "PASSED" in proc.stdout


def test_private_user_path_detected(tmp_path: Path):
    doc = tmp_path / "leak_path.md"
    doc.write_text(
        """# Review Document

Target: git -C '/Users/john_doe/code/myrepo' diff abc
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1, f"Expected returncode 1, got {proc.returncode}"
    assert "[PATH]" in proc.stderr
    assert "/Users/john_doe" in proc.stderr


def test_linux_private_user_path_detected(tmp_path: Path):
    doc = tmp_path / "leak_home_path.md"
    doc.write_text(
        """# Review Document

Target: git -C '/home/developer/workspace/app' diff abc
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1, f"Expected returncode 1, got {proc.returncode}"
    assert "[PATH]" in proc.stderr
    assert "/home/developer" in proc.stderr


def test_non_test_personal_email_detected(tmp_path: Path):
    doc = tmp_path / "leak_email.md"
    doc.write_text(
        """# Bug report

User reported an issue: contact alice_developer@gmail.com for logs.
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1, f"Expected returncode 1, got {proc.returncode}"
    assert "[EMAIL]" in proc.stderr
    assert "alice_developer@gmail.com" in proc.stderr


def test_credential_leak_detected(tmp_path: Path):
    doc = tmp_path / "leak_cred.md"
    doc.write_text(
        """# Secrets

Here is the key:
-----BEGIN RSA PRIVATE KEY-----
MIIEowIBAAKCAQEA0
-----END RSA PRIVATE KEY-----
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1, f"Expected returncode 1, got {proc.returncode}"
    assert "[CREDENTIAL]" in proc.stderr
    assert "Private key header detected" in proc.stderr


def test_password_length_leak_detected(tmp_path: Path):
    doc = tmp_path / "leak_pwd_len.md"
    doc.write_text(
        """# Issue Notes

登录失败（当前保存口令长 16 位，格式不正确）。
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1, f"Expected returncode 1, got {proc.returncode}"
    assert "[CREDENTIAL]" in proc.stderr
    assert "Password length disclosure" in proc.stderr


def test_ignore_mechanism_via_ignore_file(tmp_path: Path):
    doc = tmp_path / "ignored_leak.md"
    doc.write_text(
        """# Ignored Document

Contact: secret_user@gmail.com
Path: /Users/secret_dev/repo
""",
        encoding="utf-8",
    )

    ignore_file = tmp_path / ".sensitive_ignore"
    ignore_file.write_text("ignored_leak.md\n", encoding="utf-8")

    proc = run_checker(str(doc), "--check", "--ignore-file", str(ignore_file))
    assert proc.returncode == 0, f"Expected ignore to pass, got {proc.returncode}: {proc.stderr}"
    assert "PASSED" in proc.stdout or "No document files found" in proc.stdout


def test_ignore_mechanism_via_line_bypass(tmp_path: Path):
    doc = tmp_path / "line_bypass.md"
    doc.write_text(
        """# Document with Line Bypass

Contact: personal@gmail.com <!-- sensitive-allow -->
Path: /Users/someuser/path # noqa: sensitive
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 0, f"Expected line bypass to pass, got {proc.returncode}: {proc.stderr}"
    assert "PASSED" in proc.stdout


def test_ignore_mechanism_archived_errata(tmp_path: Path):
    archive_dir = tmp_path / "docs" / "archive"
    archive_dir.mkdir(parents=True)
    doc = archive_dir / "legacy_with_errata.md"
    doc.write_text(
        """# Legacy Document

原问题引用了 personal@gmail.com。

- 勘误注记：历史已归档文件，原内容已勘误。
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check", "--ignore-archived-errata", "--root", str(tmp_path))
    assert proc.returncode == 0, f"Expected errata exemption to pass, got {proc.returncode}: {proc.stderr}"


def test_repo_docs_gate_passes():
    proc = run_checker("--check")
    assert proc.returncode == 0, f"Current repo docs gate failed:\n{proc.stderr}\n{proc.stdout}"
    assert "PASSED" in proc.stdout
