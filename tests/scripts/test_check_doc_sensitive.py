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
    """Retirement note (A22 issue-3): the allow marker at line start used to be
    a prose prefix. With _is_isolated_assignment promoted to the scan_file gate,
    a leading standalone marker is now an accepted prefix, so the line counts as
    an isolated assignment and is actually scanned. The real intent is kept: the
    allow marker sits BEFORE the credential match, and _allowed_match_index only
    exempts matches before the marker, so this match is still reported.
    """
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
    """Retirement note (A22 issue-3): the old single prose line mixed a strong
    password into a sentence; under the _is_isolated_assignment gate that match
    is a mis-capture and is skipped, so it can no longer produce a [CREDENTIAL]
    violation. The real intent -- stderr never echoes full values -- is kept by
    splitting the credential onto its own isolated assignment line while the
    email and path remain on the prose line.
    """
    doc = tmp_path / "mixed.md"
    doc.write_text(
        "# Review\n\n"
        "Contact ops@corp.com at /Users/john_doe/repo for logs.\n"
        "PASSWORD=Sup3rSecret123\n",
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
    """Retirement note (A22 issue-3): the old line appended the lookalike token
    as bare prose after the value, which the _is_isolated_assignment gate now
    skips. The real intent -- a token that merely resembles an allow marker must
    not exempt the credential -- is kept by moving the lookalike into a trailing
    comment (an accepted isolated-assignment suffix), so the line is still
    scanned and the fake marker is still not recognised by ALLOW_MARKER_RE.
    """
    doc = tmp_path / "embedded_marker.md"
    doc.write_text(
        "# Notes\n\nPASSWORD=Sup3rSecret123 # discussed-sensitive-allow-here\n",
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


# --- A22 issue 3 regression: default-deny credential checker ----------------


def test_is_safe_credential_denies_weak_credential_shapes(monkeypatch):
    """default-deny: real weak credential shapes must be denied (False).

    The leading five used to be waived by the STRUCTURE_CHARS blanket exemption;
    12345678 used to be waived by NUMBER_LITERAL_RE. Both are now gone.
    """
    module = _load_module(monkeypatch)
    weak_shapes = [
        "my,passw0rd",
        "my(pass)word",
        "s3cr3t:VALUE",
        "foo+bar",
        "P@ssw0rd,",
        "12345678",
        "my.passw0rd",
        "supersecret",
        "correcthorsebatterystaple",
        "p@ss#word",
        "s3cr3t=VALUE",
        "abc/def",
        "x y z",
        '\"correct horse battery staple\"',
        "correct horse battery staple",
        "hunter2!",
        "Sup3rSecret123",
        "supersecret123",
    ]
    for value in weak_shapes:
        assert module.is_safe_credential(value) is False, value
        assert module.is_safe_credential(value, key="password") is False, value


def test_is_safe_credential_allows_explicit_safe_shapes(monkeypatch):
    """Only explicit safe shapes return True: placeholders/refs/code/prose.

    Retirement note (A22 issue-3): the former ("42", None) and ("3.14", None)
    numeric-literal cases are gone -- NUMBER_LITERAL_RE was removed because a
    pure numeric password such as 12345678 must be denied, not waived.
    """
    module = _load_module(monkeypatch)
    safe_shapes = [
        ("required", None),
        ("DEFAULT", None),
        ("changeme", None),
        ("dummy12345", None),
        ("your_password_here", None),
        ("True", None),
        ("FALSE", None),
        ("none", None),
        ("null", None),
        ("***", None),
        ("[REDACTED]", None),
        ("<change-me>", None),
        ("<redacted>", None),
        ("<强密码>", None),
        ("${DB_PASSWORD}", None),
        ("$(openssl rand -hex 32)", None),
        ("{{ vault_secret }}", None),
        ("os.environ['SECRET']", None),
        ("os.getenv('SECRET')", None),
        ("getenv('X')", None),
        ("process.env.SECRET", None),
        ("store.get_secret(account.credential_ref)", None),
        ("password.strip()", None),
        ("normalize_api_key(", None),
        ("password", "password"),
        ("token", "token"),
        ("mysecret", "mysecret"),
        ("这是中文说明", None),
        ("口令请见运维手册", None),
        ("...", None),
        ("=", None),
        ("false`", None),
        ("True,", None),
        ('default"`', None),
        ("default", None),
    ]
    for value, key in safe_shapes:
        assert module.is_safe_credential(value, key=key) is True, (value, key)


def test_isolated_assignment_gate_classifies_lines(monkeypatch):
    """Retirement note (A22 issue-3): is_safe_credential no longer takes a
    ``line`` argument, so the old prose-word exemption test is obsolete. Prose
    mis-captures are now filtered by the _is_isolated_assignment total gate in
    scan_file, not by a value-level exemption. This replaces it with a direct
    gate classification matrix: isolated assignments pass, prose/code snippets
    are rejected and therefore skipped.
    """
    module = _load_module(monkeypatch)
    assert (
        module._is_isolated_assignment("PASSWORD=supersecret123", "supersecret123")
        is True
    )
    assert (
        module._is_isolated_assignment(
            'password: "correct horse battery staple"', "correct horse battery staple"
        )
        is True
    )
    assert module._is_isolated_assignment("- LOGIN_PASSWORD=***", "***") is True
    assert (
        module._is_isolated_assignment(
            "Route is guarded (single password = all power) can clone", "all"
        )
        is False
    )
    assert (
        module._is_isolated_assignment(
            "W1->>DB: 短事务获取<br/>fencing_token=T", "T"
        )
        is False
    )
    assert (
        module._is_isolated_assignment("const token = await ensureCsrf()", "await")
        is False
    )


def test_default_deny_detects_weak_credential_shapes_via_cli(tmp_path):
    """CLI/scan_file regression: all five weak shapes are reported as [CREDENTIAL]."""
    doc = tmp_path / "weak.md"
    doc.write_text(
        "# Weak credentials\n\n"
        "password = my.passw0rd\n"
        "PASSWORD=correcthorsebatterystaple\n"
        "secret=abc/def\n"
        "token=s3cr3t=VALUE\n"
        'password: "correct horse battery staple"\n',
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert proc.stderr.count("[CREDENTIAL]") == 5
    for lineno in (3, 4, 5, 6, 7):
        assert f"weak.md:{lineno} [CREDENTIAL]" in proc.stderr


def test_default_deny_catches_structure_chars_and_numeric_password(tmp_path):
    """CLI regression for the two removed exemptions: values carrying the old
    STRUCTURE_CHARS characters, and a pure numeric password (old
    NUMBER_LITERAL_RE), must all be reported as [CREDENTIAL].
    """
    doc = tmp_path / "weak2.md"
    doc.write_text(
        "# Weak credentials 2\n\n"
        "password=my,passw0rd\n"
        "password=my(pass)word\n"
        "password=s3cr3t:VALUE\n"
        "password=foo+bar\n"
        "password=P@ssw0rd,\n"
        "password=12345678\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 1
    assert proc.stderr.count("[CREDENTIAL]") == 6
    for lineno in (3, 4, 5, 6, 7, 8):
        assert f"weak2.md:{lineno} [CREDENTIAL]" in proc.stderr


def test_prose_assignments_not_flagged_via_cli(tmp_path):
    """Prose/code mis-captures stay clean (prerequisite for full docs scan gating)."""
    doc = tmp_path / "prose.md"
    doc.write_text(
        "# Notes\n\n"
        "W1->>DB: 短事务获取 account_sync_leases<br/>fencing_token=T\n"
        "Route is guarded (single password = all power) can clone\n"
        "const token = await ensureCsrf()\n"
        "api_key = normalize_api_key(\n"
        "- LOGIN_PASSWORD=***\n",
        encoding="utf-8",
    )
    proc = run_checker(str(doc), "--check")
    assert proc.returncode == 0, proc.stderr
    assert "PASSED" in proc.stdout


# --- Adoption A4: opener-prefixed values are no longer a blanket exemption ---


def test_a4_opener_prefixed_values_denied(monkeypatch):
    """A4: a value merely starting with ``$``/``(``/``{``/``<`` is denied;
    template references must match the whole value (``\\Z`` anchored)."""
    module = _load_module(monkeypatch)
    for value in ("$uperSecret99", "(hiddenpass1)", "${X}tail"):
        assert module.is_safe_credential(value) is False, value
        assert module.is_safe_credential(value, key="password") is False, value
    for value in ("${X}", "$(cmd)", "{{ t }}"):
        assert module.is_safe_credential(value) is True, value


# --- Adoption A5: API references are whole-value only, never substring -------


def test_a5_api_reference_substring_denied(monkeypatch):
    """A5: a value merely containing ``os.environ`` (etc.) is denied; only a
    whole-value reference expression is safe."""
    module = _load_module(monkeypatch)
    for value in ("abc os.environ leak", "os.environ leak"):
        assert module.is_safe_credential(value) is False, value
        assert module.is_safe_credential(value, key="password") is False, value
    for value in ('os.environ["X"]', 'os.getenv("X")', "process.env.X"):
        assert module.is_safe_credential(value) is True, value
