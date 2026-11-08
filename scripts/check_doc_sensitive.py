#!/usr/bin/env python3
"""Check documents for sensitive information before commit or merge.

Detects:
1. Sensitive personal emails (excluding test/reserved domains like example.com, test.com, localhost, etc.)
2. Real host private user paths (e.g. /Users/<username> or /home/<username>)
3. Credential leak signatures (private key headers, plaintext password assignments, token signatures)
"""

from __future__ import annotations

import argparse
import fnmatch
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Iterable, Sequence

# RFC 2606 / RFC 6761 reserved & testing domains, plus official protocol documentation domains
ALLOWED_EMAIL_DOMAINS = {
    "example.com",
    "example.org",
    "example.net",
    "example.edu",
    "example.invalid",
    "test.com",
    "test.org",
    "test.net",
    "localhost",
    "invalid",
    "test",
    # Official protocol/standards documentation domains
    "ietf.org",
    "iana.org",
    "rfc-editor.org",
    "w3.org",
    # Platform documentation & notification addresses
    "github.com",
    "users.noreply.github.com",
    "noreply.github.com",
    "google.com",
    "microsoft.com",
    "apple.com",
}

# Generic/container users allowed in paths
ALLOWED_PATH_USERS = {
    "<workspace>",
    "<user_home>",
    "<local-path>",
    "<repo>",
    "<user>",
    "<username>",
    "user",
    "username",
    "runner",
    "node",
    "app",
    "appuser",
    "app_user",
    "postgres",
    "mailcore",
    "mail_core",
}

# Regex definitions
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")

# macOS and Linux user path pattern: e.g. /Users/alice or /home/bob
USER_PATH_RE = re.compile(
    r"(?:^|[\s\'\"`\(])(/(?:Users|home)/([a-zA-Z0-9._-]+)(?:/[^\s\'\"`\)]*)?)"
)
# Windows user path pattern: e.g. C:\Users\alice
WIN_USER_PATH_RE = re.compile(
    r"(?:^|[\s\'\"`\(])([A-Za-z]:\\Users\\([a-zA-Z0-9._-]+)(?:\\[^\s\'\"`\)]*)?)"
)

# Private key headers
PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:[A-Z0-9_-]+ )?PRIVATE KEY-----")

# Token leak signatures (GitHub personal access token, AWS access key, OpenAI API key)
TOKEN_RE = re.compile(
    r"\b(?:ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{82}|AKIA[0-9A-Z]{16}|sk-[a-zA-Z0-9]{32,})\b"
)

# Password length disclosure pattern (e.g. 口令长 13 位)
PWD_LEN_RE = re.compile(r"(?:口令|密码)长\s*\d+\s*位")

# Plaintext password assignment pattern
PWD_ASSIGN_RE = re.compile(
    r"(?i)\b(?:password|passwd|secret_key|api_key|access_token)\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']"
)

SAFE_CREDENTIAL_PLACEHOLDERS = {
    "***",
    "[redacted]",
    "<password>",
    "<secret>",
    "testpassword",
    "your_password_here",
}


@dataclass
class Violation:
    file_path: Path
    line_number: int
    category: str
    message: str
    matched_text: str
    line_content: str


def is_allowed_email(email: str, domain: str) -> bool:
    email_lower = email.lower()
    domain_lower = domain.lower()

    # Redacted placeholders or examples
    if "redacted" in email_lower or email_lower.startswith("user@") or email_lower.startswith("test@"):
        if any(d in domain_lower for d in ("example", "test", "invalid", "local")):
            return True

    # Check against allowed domain list and their subdomains
    for allowed in ALLOWED_EMAIL_DOMAINS:
        if domain_lower == allowed or domain_lower.endswith("." + allowed):
            return True

    return False


def is_allowed_user_path(full_path: str, username: str, line: str) -> bool:
    # Check if username is generic or a placeholder
    user_lower = username.lower()
    if user_lower in ALLOWED_PATH_USERS:
        return True
    if username.startswith("<") or username.endswith(">") or username in ("...", "xxx", "USER"):
        return True

    # Check if it's purely a regex pattern or documentation reference
    # e.g., `/Users/[^/\s]+` or `"/Users/"` or `/(Users|home)/`
    if "[^" in full_path or line.strip().startswith(("#", "//", "<!--")):
        return True
    if re.search(r"/[a-zA-Z0-9_-]+/[^/]+\[\^", full_path):
        return True

    return False


def is_safe_credential(value: str) -> bool:
    v_lower = value.lower()
    if v_lower in SAFE_CREDENTIAL_PLACEHOLDERS:
        return True
    if v_lower.startswith("$") or v_lower.startswith("{") or v_lower.startswith("<"):
        return True
    if "redacted" in v_lower or "***" in v_lower:
        return True
    return False


def load_ignore_patterns(ignore_file: Path) -> list[str]:
    patterns: list[str] = []
    if not ignore_file.is_file():
        return patterns

    text = ignore_file.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def is_ignored(
    path: Path,
    root: Path,
    ignore_patterns: Sequence[str],
) -> bool:
    try:
        rel_path = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        rel_path = path.as_posix()

    for pattern in ignore_patterns:
        # Match pattern against rel_path or path name
        if fnmatch.fnmatch(rel_path, pattern):
            return True
        if fnmatch.fnmatch(path.name, pattern):
            return True
        if pattern.endswith("/**") and rel_path.startswith(pattern[:-3]):
            return True

    return False


def scan_file(
    path: Path,
    ignore_archived_errata: bool = False,
    root: Path | None = None,
) -> list[Violation]:
    violations: list[Violation] = []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        print(f"Warning: could not read {path}: {exc}", file=sys.stderr)
        return violations

    try:
        rel_path = path.resolve().relative_to(root.resolve()).as_posix() if root else path.as_posix()
    except ValueError:
        rel_path = path.as_posix()
    is_archived = "docs/archive" in rel_path

    lines = content.splitlines()
    for lineno, line in enumerate(lines, start=1):
        # Allow line-level bypass comment
        if "sensitive-allow" in line or "noqa: sensitive" in line:
            continue

        # Precision errata line exemption: only allow historical archived lines that explicitly contain errata notice
        if ignore_archived_errata and is_archived and ("勘误注记" in line or "Errata:" in line):
            continue

        # 1. Check emails
        for m in EMAIL_RE.finditer(line):
            email = m.group(0)
            domain = m.group(1)
            # Skip false positive like npm scoped packages e.g. @types/node
            start_idx = m.start()
            if start_idx > 0 and line[start_idx - 1] == "/":
                continue

            if not is_allowed_email(email, domain):
                violations.append(
                    Violation(
                        file_path=path,
                        line_number=lineno,
                        category="email",
                        message=f"Non-test personal email detected: '{email}'",
                        matched_text=email,
                        line_content=line.strip(),
                    )
                )

        # 2. Check user host absolute paths
        for m in USER_PATH_RE.finditer(line):
            full_path = m.group(1)
            user = m.group(2)
            if not is_allowed_user_path(full_path, user, line):
                violations.append(
                    Violation(
                        file_path=path,
                        line_number=lineno,
                        category="path",
                        message=f"Host private user path detected: '{full_path}'",
                        matched_text=full_path,
                        line_content=line.strip(),
                    )
                )

        for m in WIN_USER_PATH_RE.finditer(line):
            full_path = m.group(1)
            user = m.group(2)
            if not is_allowed_user_path(full_path, user, line):
                violations.append(
                    Violation(
                        file_path=path,
                        line_number=lineno,
                        category="path",
                        message=f"Host private user path detected: '{full_path}'",
                        matched_text=full_path,
                        line_content=line.strip(),
                    )
                )

        # 3. Check credentials
        if PRIVATE_KEY_RE.search(line):
            violations.append(
                Violation(
                    file_path=path,
                    line_number=lineno,
                    category="credential",
                    message="Private key header detected",
                    matched_text=line.strip(),
                    line_content=line.strip(),
                )
            )

        m_token = TOKEN_RE.search(line)
        if m_token:
            violations.append(
                Violation(
                    file_path=path,
                    line_number=lineno,
                    category="credential",
                    message=f"API token pattern detected: '{m_token.group(0)[:10]}...'",
                    matched_text=m_token.group(0),
                    line_content=line.strip(),
                )
            )

        m_pwd_len = PWD_LEN_RE.search(line)
        if m_pwd_len:
            violations.append(
                Violation(
                    file_path=path,
                    line_number=lineno,
                    category="credential",
                    message=f"Password length disclosure detected: '{m_pwd_len.group(0)}'",
                    matched_text=m_pwd_len.group(0),
                    line_content=line.strip(),
                )
            )

        m_pwd = PWD_ASSIGN_RE.search(line)
        if m_pwd:
            val = m_pwd.group(1)
            if not is_safe_credential(val):
                violations.append(
                    Violation(
                        file_path=path,
                        line_number=lineno,
                        category="credential",
                        message=f"Plaintext password pattern detected: '{val[:3]}...'",
                        matched_text=val,
                        line_content=line.strip(),
                    )
                )

    return violations


def collect_target_files(targets: Sequence[str], root: Path) -> list[Path]:
    collected: list[Path] = []
    for target_str in targets:
        target = Path(target_str)
        if not target.is_absolute():
            target = root / target

        if target.is_file():
            collected.append(target)
        elif target.is_dir():
            for p in sorted(target.rglob("*.md")):
                if p.is_file():
                    collected.append(p)
    return collected


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check documents for sensitive information.")
    parser.add_argument(
        "targets",
        nargs="*",
        default=["docs"],
        help="Files or directories to scan (default: docs)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Return non-zero exit code if violations are found",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Repository root directory",
    )
    parser.add_argument(
        "--ignore-file",
        type=Path,
        default=None,
        help="Path to ignore file (default: .sensitive_ignore in repo root)",
    )
    parser.add_argument(
        "--ignore-archived-errata",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Allow line-level errata exemptions in historical docs under docs/archive (default: false, scan all lines)",
    )

    args = parser.parse_args(argv)

    root = args.root.resolve()
    ignore_file = args.ignore_file or (root / ".sensitive_ignore")
    ignore_patterns = load_ignore_patterns(ignore_file)

    target_files = collect_target_files(args.targets, root)
    if not target_files:
        print("No document files found to scan.")
        return 0

    all_violations: list[Violation] = []
    scanned_count = 0

    for path in target_files:
        if is_ignored(path, root, ignore_patterns):
            continue

        scanned_count += 1
        violations = scan_file(path, ignore_archived_errata=args.ignore_archived_errata, root=root)
        all_violations.extend(violations)

    if all_violations:
        print(f"\n[SENSITIVE DATA DETECTED] Found {len(all_violations)} violation(s):", file=sys.stderr)
        for v in all_violations:
            try:
                display_path = v.file_path.relative_to(root)
            except ValueError:
                display_path = v.file_path
            print(
                f"  {display_path}:{v.line_number} [{v.category.upper()}] {v.message}",
                file=sys.stderr,
            )
            print(f"    Line {v.line_number}: {v.line_content}", file=sys.stderr)

        if args.check:
            return 1
    else:
        print(f"PASSED: Checked {scanned_count} file(s), no sensitive data violations found.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
