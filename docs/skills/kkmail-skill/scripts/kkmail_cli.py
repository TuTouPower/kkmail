#!/usr/bin/env python3
"""kkmail_cli.py — Agent CLI client for kkmail.

Zero-dependency CLI tool for AI agents and automation scripts to interact
with a self-hosted kkmail (mail-core) instance via REST API.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import stat
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = os.environ.get("KKMAIL_BASE_URL") or "http://127.0.0.1:37281"
DEFAULT_PASSWORD = os.environ.get("KKMAIL_PASSWORD") or ""
DEFAULT_API_KEY = os.environ.get("KKMAIL_API_KEY") or ""


def is_loopback_host(host: str | None) -> bool:
    """Return True if host is localhost or a loopback IP address (IPv4 or IPv6)."""
    if not host:
        return False
    h = host.strip("[]").lower()
    if h == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(h)
        return ip.is_loopback
    except ValueError:
        return False


def validate_target_url(url: str) -> urllib.parse.ParseResult:
    """Validate target URL: scheme must be http/https; non-loopback targets require https."""
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme '{parsed.scheme}': only http and https are allowed.")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Invalid URL (missing host): {url}")

    if scheme == "http" and not is_loopback_host(hostname):
        raise ValueError(
            f"Insecure HTTP connection rejected: host '{hostname}' is not a loopback address "
            f"(127.0.0.1, localhost, ::1). Remote connections must use HTTPS."
        )
    return parsed


def get_url_origin(url: str) -> tuple[str, str, int]:
    """Extract (scheme, hostname, port) origin tuple from URL."""
    parsed = urllib.parse.urlparse(url)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()
    port = parsed.port
    if port is None:
        port = 443 if scheme == "https" else 80
    return (scheme, hostname, port)


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Enforces HTTPS for non-loopback redirects and strips credentials on cross-origin redirects."""

    def __init__(self, initial_url: str):
        super().__init__()
        self.initial_url = initial_url
        self.initial_origin = get_url_origin(initial_url)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target_url = urllib.parse.urljoin(req.full_url, newurl)

        # 1. Enforce scheme & loopback HTTP / remote HTTPS rules on redirect target
        try:
            validate_target_url(target_url)
        except ValueError as exc:
            raise urllib.error.HTTPError(
                target_url,
                code,
                f"Redirect rejected by security policy: {exc}",
                headers,
                fp,
            ) from exc

        old_origin = get_url_origin(req.full_url)
        new_origin = get_url_origin(target_url)
        is_cross_origin = (old_origin != new_origin)
        is_downgrade = (old_origin[0] == "https" and new_origin[0] == "http")

        # 2. Block redirecting login/credential requests across origins or downgraded transport
        if is_cross_origin or is_downgrade:
            if "/api/auth/login" in req.full_url or (req.data and "password" in str(req.data)):
                raise urllib.error.HTTPError(
                    target_url,
                    code,
                    "Redirect of login/credential payload across different origins or downgraded transport is blocked",
                    headers,
                    fp,
                )

        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is None:
            return None

        # 3. Guard credentials across boundary: never forward cookies, auth headers, or csrf tokens
        if is_cross_origin or is_downgrade:
            sensitive_headers = ["authorization", "cookie", "x-csrf-token"]
            for key in list(new_req.headers.keys()):
                if key.lower() in sensitive_headers:
                    del new_req.headers[key]
            for key in list(new_req.unredirected_hdrs.keys()):
                if key.lower() in sensitive_headers:
                    del new_req.unredirected_hdrs[key]

        return new_req


def get_default_cache_dir() -> Path:
    return Path.home() / ".cache" / "kkmail"


def get_default_cache_file() -> Path:
    return get_default_cache_dir() / "session.json"


def get_legacy_cache_file() -> Path:
    return Path.home() / ".cache" / "kkmail_agent_session.json"


class KKMailClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, api_key: str = DEFAULT_API_KEY, password: str = DEFAULT_PASSWORD):
        self.base_url = base_url.rstrip("/")
        # Validate URL immediately (loopback allows HTTP; remote requires HTTPS)
        validate_target_url(self.base_url)

        self.api_key = api_key
        self.password = password
        self.cookie: str | None = None
        self.csrf_token: str | None = None

        custom_cache = os.environ.get("KKMAIL_SESSION_CACHE")
        if custom_cache:
            self.cache_file = Path(custom_cache)
            self.is_custom_cache = True
        else:
            self.cache_file = get_default_cache_file()
            self.is_custom_cache = False

        self._opener = urllib.request.build_opener(SafeRedirectHandler(self.base_url))
        self._load_session_cache()

    def _load_session_cache(self) -> None:
        if self.api_key:
            return

        # Attempt legacy cache migration if using default path and new cache does not exist
        if not self.is_custom_cache and not self.cache_file.exists():
            legacy_file = get_legacy_cache_file()
            if legacy_file.is_file() and not legacy_file.is_symlink():
                try:
                    data = json.loads(legacy_file.read_text(encoding="utf-8"))
                    if data.get("base_url") == self.base_url:
                        self.cookie = data.get("cookie")
                        self.csrf_token = data.get("csrf_token")
                        self._save_session_cache()
                    try:
                        legacy_file.unlink()
                    except OSError:
                        pass
                    return
                except Exception:
                    pass

        # Inspect parent directory for default cache
        if not self.is_custom_cache:
            parent = self.cache_file.parent
            if parent.exists():
                if parent.is_symlink():
                    print(f"Warning: Cache directory {parent} is a symlink; skipping session cache.", file=sys.stderr)
                    return
                try:
                    os.chmod(parent, 0o700)
                except OSError:
                    pass

        # Inspect cache file
        if not self.cache_file.exists():
            return

        if self.cache_file.is_symlink():
            print(f"Warning: Session cache file {self.cache_file} is a symlink; refusing to read.", file=sys.stderr)
            return

        try:
            # Correct existing cache file permissions to 0600
            os.chmod(self.cache_file, 0o600)
        except OSError:
            pass

        try:
            data = json.loads(self.cache_file.read_text(encoding="utf-8"))
            if data.get("base_url") == self.base_url:
                self.cookie = data.get("cookie")
                self.csrf_token = data.get("csrf_token")
        except Exception:
            pass

    def _save_session_cache(self) -> None:
        if self.api_key or not self.cookie:
            return

        parent = self.cache_file.parent

        if not self.is_custom_cache:
            # Default path: ensure dedicated 0700 directory
            if parent.is_symlink():
                print(f"Warning: Cache directory {parent} is a symlink; refusing to save session.", file=sys.stderr)
                return
            try:
                parent.mkdir(parents=True, exist_ok=True)
                os.chmod(parent, 0o700)
            except OSError as exc:
                print(f"Warning: Could not create private cache directory {parent}: {exc}", file=sys.stderr)
                return
        else:
            # Custom path: ensure parent exists, but do NOT modify user's shared parent directory permissions
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                print(f"Warning: Could not create parent directory {parent}: {exc}", file=sys.stderr)
                return

        # Refuse to overwrite if target is already a symlink
        if self.cache_file.is_symlink():
            print(f"Warning: Session cache file {self.cache_file} is a symlink; refusing to overwrite.", file=sys.stderr)
            return

        data = {"base_url": self.base_url, "cookie": self.cookie, "csrf_token": self.csrf_token}
        payload = json.dumps(data, indent=2).encode("utf-8")

        # Write to temporary file in the same directory, sync to disk, and replace atomically
        tmp_fd = None
        tmp_path = None
        try:
            tmp_fd, tmp_path_str = tempfile.mkstemp(prefix=".session_", suffix=".tmp", dir=str(parent))
            tmp_path = Path(tmp_path_str)
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass

            with os.fdopen(tmp_fd, "wb") as f:
                tmp_fd = None  # os.fdopen takes ownership
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())

            # Double-check target before replacing
            if self.cache_file.is_symlink():
                raise RuntimeError(f"Session cache file {self.cache_file} is a symlink; aborting replacement.")

            os.replace(tmp_path, self.cache_file)
            try:
                os.chmod(self.cache_file, 0o600)
            except OSError:
                pass
        except Exception as exc:
            if tmp_fd is not None:
                try:
                    os.close(tmp_fd)
                except OSError:
                    pass
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            print(f"Warning: Failed to save session cache: {exc}", file=sys.stderr)

    def login(self) -> bool:
        if self.api_key:
            return True
        if not self.password:
            print(
                "Error: Authentication password required. Set KKMAIL_PASSWORD or pass --password.",
                file=sys.stderr,
            )
            return False
        url = f"{self.base_url}/api/auth/login"
        payload = json.dumps({"password": self.password}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self._opener.open(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                self.csrf_token = data.get("csrf_token")
                cookie_header = resp.headers.get("Set-Cookie")
                if cookie_header:
                    self.cookie = cookie_header.split(";")[0]
                self._save_session_cache()
                return True
        except Exception as exc:
            print(f"Error logging in to kkmail at {self.base_url}: {exc}", file=sys.stderr)
            return False

    def request(self, method: str, path: str, params: dict | None = None, data: dict | None = None, retry: bool = True) -> dict:
        url = f"{self.base_url}{path}"
        if params:
            query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
            if query:
                url = f"{url}?{query}"

        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        else:
            if not self.cookie and not self.login():
                raise RuntimeError(f"Authentication failed for {self.base_url}")
            if self.cookie:
                headers["Cookie"] = self.cookie
            if self.csrf_token and method in ("POST", "PUT", "DELETE", "PATCH"):
                headers["X-CSRF-Token"] = self.csrf_token

        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(data).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=30) as resp:
                text = resp.read().decode("utf-8")
                if not text.strip():
                    return {"ok": True, "status_code": resp.status}
                return json.loads(text)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403) and retry and not self.api_key:
                if self.login():
                    return self.request(method, path, params, data, retry=False)
            error_body = exc.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(error_body)
                raise RuntimeError(f"HTTP {exc.code} {path}: {err_json.get('detail', error_body)}") from exc
            except json.JSONDecodeError:
                raise RuntimeError(f"HTTP {exc.code} {path}: {error_body}") from exc

    # High-level actions
    def health(self) -> dict:
        req = urllib.request.Request(
            f"{self.base_url}/health",
            headers={"Accept": "application/json"},
            method="GET",
        )
        with self._opener.open(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            if not body.strip():
                return {"ok": True, "status_code": resp.status}
            return json.loads(body)

    def stats(self) -> dict:
        return self.request("GET", "/api/mail/stats")

    def list_accounts(self) -> list[dict]:
        res = self.request("GET", "/api/accounts")
        return res if isinstance(res, list) else res.get("accounts", [])

    def sync_account(self, account_id: str | None = None) -> dict:
        if account_id:
            return self.request("POST", f"/api/accounts/{account_id}/sync")
        return self.request("POST", "/api/accounts/sync-all")

    def add_account(self, email: str, provider: str, credentials: dict, config: dict | None = None) -> dict:
        payload = {"email": email, "provider": provider, "credentials": credentials}
        if config:
            payload["config"] = config
        return self.request("POST", "/api/accounts", data=payload)

    def delete_account(self, account_id: str) -> dict:
        return self.request("DELETE", f"/api/accounts/{account_id}")

    def list_inbox(
        self,
        limit: int = 20,
        account_id: str | None = None,
        folder_id: str | None = None,
        unread_only: bool = False,
        flagged_only: bool = False,
        cursor: str | None = None,
    ) -> dict:
        params: dict = {"limit": limit}
        if account_id:
            params["account_id"] = account_id
        if folder_id:
            params["folder_id"] = folder_id
        if unread_only:
            params["is_read"] = "false"
        if flagged_only:
            params["is_flagged"] = "true"
        if cursor:
            params["cursor"] = cursor
        return self.request("GET", "/api/mail/inbox", params=params)

    def search(self, query: str, limit: int = 20, account_id: str | None = None) -> dict:
        params: dict = {"q": query, "limit": limit}
        if account_id:
            params["account_id"] = account_id
        return self.request("GET", "/api/mail/search", params=params)

    def get_message(self, message_id: str) -> dict:
        return self.request("GET", f"/api/mail/messages/{message_id}")

    def mark_message(self, message_id: str, action: str) -> dict:
        """action in ('read', 'unread', 'star', 'unstar', 'trash')"""
        if action == "read":
            return self.request("POST", f"/api/mail/messages/{message_id}/read", data={"is_read": True})
        if action == "unread":
            return self.request("POST", f"/api/mail/messages/{message_id}/read", data={"is_read": False})
        if action == "star":
            return self.request("POST", f"/api/mail/messages/{message_id}/flag", data={"is_flagged": True})
        if action == "unstar":
            return self.request("POST", f"/api/mail/messages/{message_id}/flag", data={"is_flagged": False})
        if action == "trash":
            return self.request("POST", f"/api/mail/messages/{message_id}/trash", data={})
        raise ValueError(f"Unknown mark action: {action}")


def print_json(data: object) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def format_read_status(is_read: bool | None) -> str:
    if is_read is True:
        return "✓"
    if is_read is False:
        return "●"
    return "-"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="kkmail Agent CLI client. Interacts with kkmail instance over HTTP (loopback only) or HTTPS (remote)."
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    parser.add_argument(
        "--url",
        default=DEFAULT_BASE_URL,
        help="kkmail base URL (defaults to http://127.0.0.1:37281; HTTPS required for remote non-loopback)",
    )
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Login password (prefer KKMAIL_PASSWORD env var)")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="Bearer API key (prefer KKMAIL_API_KEY env var)")

    sub = parser.add_subparsers(dest="cmd", required=True)

    # health / status
    sub.add_parser("health", help="Check kkmail service health")

    # stats
    sub.add_parser("stats", help="Get unread email stats across accounts")

    # accounts
    p_acc = sub.add_parser("accounts", help="List accounts")
    p_acc.add_argument("--sync", action="store_true", help="Trigger sync for all accounts")

    # sync
    p_sync = sub.add_parser("sync", help="Trigger email sync")
    p_sync.add_argument("account_id", nargs="?", help="Optional account ID to sync single account")

    # list
    p_list = sub.add_parser("list", help="List inbox emails")
    p_list.add_argument("--limit", type=int, default=20, help="Max emails to return")
    p_list.add_argument("--account", help="Filter by account ID")
    p_list.add_argument("--unread", action="store_true", help="Only show unread emails")
    p_list.add_argument("--flagged", action="store_true", help="Only show flagged/starred emails")
    p_list.add_argument("--cursor", help="Pagination cursor")

    # search
    p_search = sub.add_parser("search", help="Full-text search emails")
    p_search.add_argument("query", help="Search query (supports Chinese and English)")
    p_search.add_argument("--limit", type=int, default=20, help="Max results")
    p_search.add_argument("--account", help="Filter by account ID")

    # read
    p_read = sub.add_parser("read", help="Read email metadata, body and attachments")
    p_read.add_argument("message_id", help="Message ID")
    p_read.add_argument("--body-only", action="store_true", help="Only print plain text body")

    # mark
    p_mark = sub.add_parser("mark", help="Mark message status (read, unread, star, unstar, trash)")
    p_mark.add_argument("message_id", help="Message ID")
    p_mark.add_argument("action", choices=["read", "unread", "star", "unstar", "trash"], help="Action to apply")

    # add-account
    p_add = sub.add_parser("add-account", help="Add an email account")
    p_add.add_argument("--email", required=True, help="Email address")
    p_add.add_argument("--provider", default="imap", choices=["imap", "gmail", "graph"], help="Provider")
    p_add.add_argument("--host", help="IMAP server host")
    p_add.add_argument("--port", type=int, default=993, help="IMAP port")
    p_add.add_argument("--no-ssl", action="store_true", help="Disable SSL/TLS for IMAP")
    p_add.add_argument("--password", dest="acc_password", help="Account password (prefer KKMAIL_ACCOUNT_PASSWORD env var)")
    p_add.add_argument("--credentials-json", help="Raw JSON string for credentials")

    args = parser.parse_args()

    try:
        client = KKMailClient(base_url=args.url, api_key=args.api_key, password=args.password)

        if args.cmd == "health":
            res = client.health()
            if args.json:
                print_json(res)
            else:
                print(f"kkmail status: {res.get('status')} (service: {res.get('service')}, schema: {res.get('schema_head')})")

        elif args.cmd == "stats":
            res = client.stats()
            if args.json:
                print_json(res)
            else:
                total_unread = res.get("total_unread")
                print(f"Total unread messages: {total_unread if total_unread is not None else '-'}")
                for acc in res.get("accounts", []):
                    acc_id = acc.get("account_id")
                    unread = acc.get("unread_count", 0)
                    total = acc.get("total_count", 0)
                    print(f"  - Account {acc_id}: {unread} unread / {total} total")

        elif args.cmd == "accounts":
            if getattr(args, "sync", False):
                client.sync_account()
                print("All accounts queued for sync.")
            items = client.list_accounts()
            if args.json:
                print_json(items)
            else:
                print(f"Accounts ({len(items)}):")
                for a in items:
                    print(f"  [{a.get('provider')}] {a.get('email')} (id: {a.get('id')}) - status: {a.get('sync_status')}")

        elif args.cmd == "sync":
            res = client.sync_account(args.account_id)
            if args.json:
                print_json(res)
            else:
                print(f"Sync queued successfully: {res}")

        elif args.cmd == "list":
            res = client.list_inbox(
                limit=args.limit,
                account_id=args.account,
                unread_only=args.unread,
                flagged_only=args.flagged,
                cursor=args.cursor,
            )
            if args.json:
                print_json(res)
            else:
                items = res.get("items", [])
                print(f"Messages ({len(items)}) | Next cursor: {res.get('next_cursor') or 'None'}:")
                for m in items:
                    read_flag = format_read_status(m.get("is_read"))
                    star_flag = "★" if m.get("is_flagged") else " "
                    subj = m.get("subject") or "(No Subject)"
                    from_name = m.get("from_name") or m.get("from_address") or ""
                    date = m.get("date") or m.get("sort_time") or ""
                    print(f"  {read_flag} {star_flag} [{m.get('id')}] {date[:16]:16s} {from_name[:24]:24s} {subj}")

        elif args.cmd == "search":
            res = client.search(query=args.query, limit=args.limit, account_id=args.account)
            if args.json:
                print_json(res)
            else:
                items = res.get("items", [])
                print(f"Search results for '{args.query}' ({len(items)}):")
                for m in items:
                    read_flag = format_read_status(m.get("is_read"))
                    star_flag = "★" if m.get("is_flagged") else " "
                    subj = m.get("subject") or "(No Subject)"
                    from_name = m.get("from_name") or m.get("from_address") or ""
                    print(f"  {read_flag} {star_flag} [{m.get('id')}] {from_name[:24]:24s} {subj}")

        elif args.cmd == "read":
            msg = client.get_message(args.message_id)
            if args.json:
                print_json(msg)
            elif args.body_only:
                print(msg.get("body") or msg.get("snippet") or "(Empty body)")
            else:
                print(f"Subject: {msg.get('subject')}")
                print(f"From:    {msg.get('from_') or msg.get('from_address')}")
                print(f"To:      {msg.get('to')}")
                print(f"Date:    {msg.get('date')}")
                print(f"Flags:   {'[Read]' if msg.get('is_read') else '[Unread]'} {'[Flagged]' if msg.get('is_flagged') else ''}")
                attachments = msg.get("attachments", [])
                if attachments:
                    print(f"Attachments ({len(attachments)}): {', '.join(a.get('name', '') for a in attachments)}")
                print("-" * 60)
                body_text = msg.get("body") or msg.get("snippet") or "(Empty body)"
                print(body_text.strip())

        elif args.cmd == "mark":
            res = client.mark_message(args.message_id, args.action)
            if args.json:
                print_json(res)
            else:
                print(f"Message {args.message_id} marked as '{args.action}': {res}")

        elif args.cmd == "add-account":
            creds = {}
            acc_pass = args.acc_password or os.environ.get("KKMAIL_ACCOUNT_PASSWORD")
            if args.credentials_json:
                creds = json.loads(args.credentials_json)
            elif acc_pass:
                creds = {"password": acc_pass}

            cfg = None
            if args.provider == "imap" and args.host:
                cfg = {"imap_host": args.host, "imap_port": args.port, "use_ssl": not args.no_ssl}
            res = client.add_account(args.email, args.provider, creds, cfg)
            if args.json:
                print_json(res)
            else:
                print(f"Account added successfully: {res.get('id')} ({args.email})")

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
