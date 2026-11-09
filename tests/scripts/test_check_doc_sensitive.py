"""Tests for doc sensitivity checker (scripts/check_doc_sensitive.py).

Value-echo tests were removed: Violation.message is deleted and redact() is the
single output surface (category + file + line only), so assertions that a full
email / host path / password / message appears in stderr are obsolete. Replaced
by tests asserting the redact() contract and that no full value reaches stderr.
"""

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


def _load_module(monkeypatch):
    spec = importlib.util.spec_from_file_location("check_doc_sensitive_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


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


def test_missing_target_returns_nonzero(tmp_path: Path):
    missing = tmp_path / "does_not_exist.md"
    proc = run_checker(str(missing), "--check")
    assert proc.returncode == 2
    assert "does not exist" in proc.stderr


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


def test_repo_docs_gate_passes():
    proc = run_checker("--check")
    assert proc.returncode == 0, f"Current repo docs gate failed: {proc.stderr} {proc.stdout}"
    assert "PASSED" in proc.stdout


def test_redact_output_is_only_category_file_line(tmp_path: Path, monkeypatch):
    module = _load_module(monkeypatch)
    root = tmp_path
    doc = root / "nested" / "leak.md"
    violation = module.Violation(
        file_path=doc,
        line_number=7,
        category="credential",
        matched_text="Sup3rSecret123",
    )
    out = module.redact(violation, root)
    assert out == "nested/leak.md:7 [CREDENTIAL]"
    assert "Sup3rSecret123" not in out
    assert not hasattr(violation, "message")

    outside = Path("/var/folders/elsewhere/secret.md")
    out2 = module.redact(
        module.Violation(
            file_path=outside,
            line_number=2,
            category="email",
            matched_text="a@b.com",
        ),
        root,
    )
    assert out2 == "secret.md:2 [EMAIL]"
    assert "a@b.com" not in out2


def test_five_credential_shapes_all_detected(tmp_path: Path):
    doc = tmp_path / "shapes.md"
    doc.write_text(
        "# Config\n\n"
        "DB_PASSWORD=Sup3rSecret123\n"
        "MAIL_CORE_LOGIN_PASSWORD=Sup3rSecret123\n"
        "PASSWORD = Sup3rSecret123\n"
        "password: supersecret123\n"
        "PASSWORD=Sup3rSecret123\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert proc.stderr.count("[CREDENTIAL]") == 5
    for lineno in (3, 4, 5, 6, 7):
        assert f"shapes.md:{lineno} [CREDENTIAL]" in proc.stderr
    assert "Sup3rSecret123" not in proc.stderr
    assert "supersecret123" not in proc.stderr


def test_code_identifiers_and_placeholders_not_flagged(tmp_path: Path):
    doc = tmp_path / "code.md"
    doc.write_text(
        "# Archived notes\n\n"
        "self.password = password.strip()\n"
        "payload = data.get(\n"
        "api_key = normalize_api_key(\n"
        "secret = store.get_secret(...)\n"
        "mode = default\n"
        "mask = ***\n"
        "LOGIN_PASSWORD=***\n"
        "client_secret=required\n"
        "hide_password=True\n"
        "这段中文散文描述了登录流程与凭据处理，不含任何真实值。\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 0, proc.stderr
    assert "PASSED" in proc.stdout


def test_weak_placeholders_allowed(tmp_path: Path):
    doc = tmp_path / "weak_pwd.md"
    doc.write_text(
        "# Config Notes\n\n"
        "password: \"changeme\"\n"
        "api_key = 'dummy12345'\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 0, proc.stderr
    assert "PASSED" in proc.stdout


def test_stderr_never_echoes_full_values(tmp_path: Path):
    doc = tmp_path / "mixed.md"
    doc.write_text(
        "# Review\n\n"
        "Contact ops@corp.com at /Users/john_doe/repo with password=Sup3rSecret123\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    combined = proc.stdout + proc.stderr
    assert "ops@corp.com" not in combined
    assert "/Users/john_doe" not in combined
    assert "Sup3rSecret123" not in combined
    assert "[EMAIL]" in proc.stderr
    assert "[PATH]" in proc.stderr
    assert "[CREDENTIAL]" in proc.stderr
    assert "[REDACTED]" not in proc.stderr
    assert "chars withheld" not in proc.stderr


def test_macos_user_path_detected_with_redacted_output(tmp_path: Path):
    doc = tmp_path / "leak_path.md"
    doc.write_text(
        "# Review Document\n\n"
        "Target: git -C '/Users/john_doe/code/myrepo' diff abc\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "leak_path.md:3 [PATH]" in proc.stderr
    assert "/Users/john_doe" not in proc.stderr


def test_linux_user_path_detected_with_redacted_output(tmp_path: Path):
    doc = tmp_path / "leak_home_path.md"
    doc.write_text(
        "# Review Document\n\n"
        "Target: git -C '/home/developer/workspace/app' diff abc\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "leak_home_path.md:3 [PATH]" in proc.stderr
    assert "/home/developer" not in proc.stderr


def test_windows_user_path_detected_with_redacted_output(tmp_path: Path):
    doc = tmp_path / "win_path_eq.md"
    doc.write_text(
        "# Review Document\n\nTarget: path=C:\\Users\\john_doe\\repo cache\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "win_path_eq.md:3 [PATH]" in proc.stderr
    assert "C:\\Users\\john_doe" not in proc.stderr


def test_personal_email_detected_with_redacted_output(tmp_path: Path):
    doc = tmp_path / "leak_email.md"
    doc.write_text(
        "# Bug report\n\n"
        "User reported an issue: contact alice_developer@gmail.com for logs.\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "leak_email.md:3 [EMAIL]" in proc.stderr
    assert "alice_developer@gmail.com" not in proc.stderr


def test_path_equals_form_detected_with_fake_user(tmp_path: Path):
    doc = tmp_path / "path_eq.md"
    doc.write_text(
        "# Review Document\n\n"
        "Target: path=/Users/example.user/code/myrepo diff abc\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "path_eq.md:3 [PATH]" in proc.stderr
    assert "/Users/example.user" not in proc.stderr


def test_credential_signatures_detected_with_redacted_output(tmp_path: Path):
    cases = [
        ("bare.md", "# Notes\n\nPASSWORD=Sup3rSecret!value\n", "Sup3rSecret!value"),
        (
            "key.md",
            "# Notes\n\nHere is the key:\n-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEA0\n-----END RSA PRIVATE KEY-----\n",
            "-----BEGIN RSA PRIVATE KEY-----",
        ),
        (
            "pwdlen.md",
            "# Notes\n\n登录失败（当前保存口令长 16 位，格式不正确）。\n",
            "口令长 16 位",
        ),
        (
            "token.md",
            "# Notes\n\napi token: sk-proj-Ab3Cd9Ef0Gh1Ij2Kl3Mn4Op5Qr6St7-_Zx\n",
            "sk-proj-Ab3Cd9Ef0Gh1Ij2Kl3Mn4Op5Qr6St7-_Zx",
        ),
    ]
    for name, content, secret in cases:
        doc = tmp_path / name
        doc.write_text(content, encoding="utf-8")
        proc = run_checker(str(doc), "--check")
        assert proc.returncode == 1, (name, proc.stderr)
        assert "[CREDENTIAL]" in proc.stderr, (name, proc.stderr)
        assert secret not in proc.stderr, (name, proc.stderr)
        assert "Private key header detected" not in proc.stderr
        assert "API token pattern detected" not in proc.stderr
        assert "Plaintext password pattern detected" not in proc.stderr
        assert "Password length disclosure" not in proc.stderr


def test_inline_allow_exempts_only_nearest_match(tmp_path: Path, monkeypatch):
    doc = tmp_path / "inline_allow.md"
    doc.write_text(
        "# Review Document\n\n"
        "Contact alice@corp.com and bob@corp.com <!-- sensitive-allow -->\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert proc.stderr.count("[EMAIL]") == 1
    assert "inline_allow.md:3 [EMAIL]" in proc.stderr
    assert "alice@corp.com" not in proc.stderr
    assert "bob@corp.com" not in proc.stderr

    module = _load_module(monkeypatch)
    remaining = module.scan_file(doc, root=tmp_path)
    assert [v.matched_text for v in remaining] == ["alice@corp.com"]


def test_archived_errata_cannot_hide_sensitive_line(tmp_path: Path):
    archive_dir = tmp_path / "docs" / "archive"
    archive_dir.mkdir(parents=True)
    doc = archive_dir / "legacy_with_errata.md"
    doc.write_text(
        "# Legacy Document\n\n"
        "原问题引用了 personal@gmail.com。\n\n"
        "- 勘误注记：历史已归档文件，原内容已勘误。\n",
        encoding="utf-8",
    )
    for extra in ([], ["--ignore-archived-errata"]):
        proc = run_checker(str(doc), "--check", "--root", str(tmp_path), *extra)
        assert proc.returncode == 1, (extra, proc.stderr)
        assert "[EMAIL]" in proc.stderr
        assert "personal@gmail.com" not in proc.stderr


def test_archived_errata_precision_line_exemption(tmp_path: Path):
    archive_dir = tmp_path / "docs" / "archive"
    archive_dir.mkdir(parents=True)
    doc = archive_dir / "line_errata.md"
    doc.write_text(
        "# Archived Document\n\n"
        "- 勘误注记：历史已归档说明中曾提及 legacy_user@gmail.com 已闭环。\n",
        encoding="utf-8",
    )
    proc_strict = run_checker(
        str(doc), "--check", "--no-ignore-archived-errata", "--root", str(tmp_path)
    )
    assert proc_strict.returncode == 1
    assert "[EMAIL]" in proc_strict.stderr
    assert "legacy_user@gmail.com" not in proc_strict.stderr

    proc_allowed = run_checker(
        str(doc), "--check", "--ignore-archived-errata", "--root", str(tmp_path)
    )
    assert proc_allowed.returncode == 0, proc_allowed.stderr


def test_empty_existing_directory_returns_nonzero(tmp_path: Path):
    empty = tmp_path / "empty_docs"
    empty.mkdir()
    proc = run_checker(str(empty), "--check")
    assert proc.returncode == 2
    assert "no document files found" in proc.stderr


def test_line_bypass_requires_independent_marker(tmp_path: Path):
    doc = tmp_path / "embedded_marker.md"
    doc.write_text(
        "# Notes\n\nPASSWORD=Sup3rSecret123 discussed-sensitive-allow-here\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "embedded_marker.md:3 [CREDENTIAL]" in proc.stderr
    assert "Sup3rSecret123" not in proc.stderr


def test_comment_start_does_not_exempt_real_path(tmp_path: Path):
    doc = tmp_path / "comment_path.md"
    doc.write_text(
        "# Notes\n\n<!-- see /Users/realuser/private_notes.md for context -->\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert "comment_path.md:3 [PATH]" in proc.stderr
    assert "/Users/realuser" not in proc.stderr
