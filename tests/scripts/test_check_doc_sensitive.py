"""Tests for doc sensitivity checker (scripts/check_doc_sensitive.py)."""

from __future__ import annotations

import importlib.util
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


def test_archived_errata_whole_file_bypass_eliminated(tmp_path: Path):
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

    # Default run: whole-file errata bypass is eliminated, sensitive line must be caught
    proc_default = run_checker(str(doc), "--check", "--root", str(tmp_path))
    assert proc_default.returncode == 1, "Expected violation to be caught under default settings"
    assert "personal@gmail.com" in proc_default.stderr

    # Even with --ignore-archived-errata, the non-annotated sensitive line must still be caught
    proc_flag = run_checker(str(doc), "--check", "--ignore-archived-errata", "--root", str(tmp_path))
    assert proc_flag.returncode == 1, "Expected non-annotated sensitive line to be caught even with --ignore-archived-errata"
    assert "personal@gmail.com" in proc_flag.stderr


def test_archived_errata_line_level_precision(tmp_path: Path):
    archive_dir = tmp_path / "docs" / "archive"
    archive_dir.mkdir(parents=True)
    doc = archive_dir / "line_errata.md"
    doc.write_text(
        """# Archived Document

- 勘误注记：历史已归档说明中曾提及 legacy_user@gmail.com 已闭环。
""",
        encoding="utf-8",
    )

    # Default: strict line-by-line scanning catches it
    proc_strict = run_checker(str(doc), "--check", "--no-ignore-archived-errata", "--root", str(tmp_path))
    assert proc_strict.returncode == 1
    assert "legacy_user@gmail.com" in proc_strict.stderr

    # With precision line exemption: only lines containing errata notice are allowed
    proc_allowed = run_checker(str(doc), "--check", "--ignore-archived-errata", "--root", str(tmp_path))
    assert proc_allowed.returncode == 0, f"Expected precision line exemption to pass: {proc_allowed.stderr}"


def test_weak_password_placeholder_rejected(tmp_path: Path):
    doc = tmp_path / "weak_pwd.md"
    doc.write_text(
        """# Config Notes

password: "changeme"
api_key = 'dummy12345'
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1, f"Expected weak passwords to be rejected, got {proc.returncode}"
    assert "[CREDENTIAL]" in proc.stderr
    assert "Plaintext password pattern detected" in proc.stderr


def test_gate_output_redacts_secrets(tmp_path: Path):
    doc = tmp_path / "redact.md"
    doc.write_text(
        """# Config Notes

password: "supersecret123" and contact ops@corp.com
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert "supersecret123" not in combined
    assert 'password: "supersecret123" and contact ops@corp.com' not in combined
    assert "[REDACTED]" in proc.stderr


def test_path_equals_user_path_detected(tmp_path: Path):
    doc = tmp_path / "path_eq.md"
    doc.write_text(
        """# Review Document

Target: path=/Users/john_doe/code/myrepo diff abc
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "[PATH]" in proc.stderr
    assert "/Users/john_doe" in proc.stderr


def test_win_path_equals_user_path_detected(tmp_path: Path):
    doc = tmp_path / "win_path_eq.md"
    doc.write_text(
        "# Review Document\n\nTarget: path=C:\\Users\\john_doe\\repo cache\n",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "[PATH]" in proc.stderr
    assert "C:\\Users\\john_doe" in proc.stderr


def test_unquoted_password_assignment_detected(tmp_path: Path):
    doc = tmp_path / "bare_pwd.md"
    doc.write_text(
        """# Config Notes

PASSWORD=secret
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "[CREDENTIAL]" in proc.stderr
    assert "Plaintext password pattern detected" in proc.stderr


def test_sk_proj_token_detected(tmp_path: Path):
    token = "sk-proj-" + "A" * 40
    doc = tmp_path / "sk_proj.md"
    doc.write_text(
        f"# Secrets\n\napi token: {token}\n",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "[CREDENTIAL]" in proc.stderr
    assert "API token pattern detected" in proc.stderr


def test_missing_target_returns_nonzero(tmp_path: Path):
    missing = tmp_path / "does_not_exist.md"
    proc = run_checker(str(missing), "--check")
    assert proc.returncode == 2
    assert "does not exist" in proc.stderr


def test_empty_existing_directory_still_passes(tmp_path: Path):
    empty = tmp_path / "empty_docs"
    empty.mkdir()
    proc = run_checker(str(empty), "--check")
    assert proc.returncode == 0
    assert "No document files found to scan." in proc.stdout


def test_scan_file_streams_without_read_text(tmp_path: Path, monkeypatch):
    spec = importlib.util.spec_from_file_location("check_doc_sensitive_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)

    doc = tmp_path / "stream.md"
    doc.write_text("Contact: alice_developer@gmail.com\n", encoding="utf-8")

    def forbid_read_text(*args, **kwargs):
        raise AssertionError("scan_file must not load the whole file via read_text")

    monkeypatch.setattr(Path, "read_text", forbid_read_text)

    violations = module.scan_file(doc, root=tmp_path)
    assert [v.category for v in violations] == ["email"]


def test_inline_allow_reports_other_secrets_on_same_line(tmp_path: Path):
    doc = tmp_path / "inline_allow.md"
    doc.write_text(
        """# Review Document

Contact alice@corp.com and bob@corp.com <!-- sensitive-allow -->
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "alice@corp.com" in proc.stderr
    assert "bob@corp.com" not in proc.stderr


def test_inline_allow_does_not_exempt_match_after_marker(tmp_path: Path):
    doc = tmp_path / "allow_after.md"
    doc.write_text(
        """# Review Document

<!-- sensitive-allow --> PASSWORD=supersecret123
""",
        encoding="utf-8",
    )

    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "[CREDENTIAL]" in proc.stderr


def test_gate_on_clean_tree_passes(tmp_path: Path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "clean.md").write_text(
        """# Clean Document

Contact: user@example.com
Path: /home/runner/work
""",
        encoding="utf-8",
    )

    proc = run_checker("docs", "--check", "--root", str(tmp_path))
    assert proc.returncode == 0, proc.stderr
    assert "PASSED" in proc.stdout
