#!/usr/bin/env python3
"""kkmail_cli.py — Agent CLI client for kkmail.

Zero-dependency CLI tool for AI agents and automation scripts to interact
with a self-hosted kkmail (mail-core) instance via REST API.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = os.environ.get("KKMAIL_BASE_URL") or "http://127.0.0.1:37281"
DEFAULT_PASSWORD = (
    os.environ.get("KKMAIL_PASSWORD")
    or os.environ.get("MAIL_CORE_LOGIN_PASSWORD")
    or os.environ.get("LOGIN_PASSWORD")
    or "admin123456Password!"
)
DEFAULT_API_KEY = os.environ.get("KKMAIL_API_KEY") or os.environ.get("MAIL_CORE_API_KEYS") or ""
SESSION_CACHE_FILE = Path(os.environ.get("KKMAIL_SESSION_CACHE") or (Path.home() / ".cache" / "kkmail_agent_session.json"))


class KKMailClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, api_key: str = DEFAULT_API_KEY, password: str = DEFAULT_PASSWORD):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.password = password.strip()
        self.cookie: str | None = None
        self.csrf_token: str | None = None
        self._load_session_cache()

    def _load_session_cache(self) -> None:
        if self.api_key:
            return
        if SESSION_CACHE_FILE.is_file():
            try:
                data = json.loads(SESSION_CACHE_FILE.read_text(encoding="utf-8"))
                if data.get("base_url") == self.base_url:
                    self.cookie = data.get("cookie")
                    self.csrf_token = data.get("csrf_token")
            except Exception:
                pass

    def _save_session_cache(self) -> None:
        if self.api_key or not self.cookie:
            return
        try:
            SESSION_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            data = {"base_url": self.base_url, "cookie": self.cookie, "csrf_token": self.csrf_token}
            SESSION_CACHE_FILE.write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    def login(self) -> bool:
        if self.api_key:
            return True
        url = f"{self.base_url}/api/auth/login"
        payload = json.dumps({"password": self.password}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
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
            with urllib.request.urlopen(req, timeout=30) as resp:
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
        return self.request("GET", "/health")

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
            params["unread_only"] = "true"
        if flagged_only:
            params["flagged_only"] = "true"
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


def main() -> None:
    # Pre-parse --json so it works globally regardless of position
    output_json = "--json" in sys.argv
    cleaned_argv = [a for a in sys.argv[1:] if a != "--json"]

    parser = argparse.ArgumentParser(description="kkmail Agent CLI client")
    parser.add_argument("--url", default=DEFAULT_BASE_URL, help="kkmail base URL")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Login password")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY, help="Bearer API key")

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
    p_add.add_argument("--password", dest="acc_password", help="Account password")
    p_add.add_argument("--credentials-json", help="Raw JSON string for credentials")

    args = parser.parse_args(cleaned_argv)
    client = KKMailClient(base_url=args.url, api_key=args.api_key, password=args.password)

    try:
        if args.cmd == "health":
            res = client.health()
            if output_json:
                print_json(res)
            else:
                print(f"kkmail status: {res.get('status')} (service: {res.get('service')}, schema: {res.get('schema_head')})")

        elif args.cmd == "stats":
            res = client.stats()
            if output_json:
                print_json(res)
            else:
                print(f"Total unread messages: {res.get('total_unread', 0)}")
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
            if output_json:
                print_json(items)
            else:
                print(f"Accounts ({len(items)}):")
                for a in items:
                    print(f"  [{a.get('provider')}] {a.get('email')} (id: {a.get('id')}) - status: {a.get('sync_status')}")

        elif args.cmd == "sync":
            res = client.sync_account(args.account_id)
            if output_json:
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
            if output_json:
                print_json(res)
            else:
                items = res.get("items", [])
                print(f"Messages ({len(items)}) | Next cursor: {res.get('next_cursor') or 'None'}:")
                for m in items:
                    read_flag = " " if m.get("is_read") else "●"
                    star_flag = "★" if m.get("is_flagged") else " "
                    subj = m.get("subject") or "(No Subject)"
                    from_name = m.get("from_name") or m.get("from_address") or ""
                    date = m.get("date") or m.get("sort_time") or ""
                    print(f"  {read_flag} {star_flag} [{m.get('id')}] {date[:16]:16s} {from_name[:24]:24s} {subj}")

        elif args.cmd == "search":
            res = client.search(query=args.query, limit=args.limit, account_id=args.account)
            if output_json:
                print_json(res)
            else:
                items = res.get("items", [])
                print(f"Search results for '{args.query}' ({len(items)}):")
                for m in items:
                    read_flag = " " if m.get("is_read") else "●"
                    star_flag = "★" if m.get("is_flagged") else " "
                    subj = m.get("subject") or "(No Subject)"
                    from_name = m.get("from_name") or m.get("from_address") or ""
                    print(f"  {read_flag} {star_flag} [{m.get('id')}] {from_name[:24]:24s} {subj}")

        elif args.cmd == "read":
            msg = client.get_message(args.message_id)
            if output_json:
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
            if output_json:
                print_json(res)
            else:
                print(f"Message {args.message_id} marked as '{args.action}': {res}")

        elif args.cmd == "add-account":
            creds = {}
            if args.credentials_json:
                creds = json.loads(args.credentials_json)
            elif args.acc_password:
                creds = {"password": args.acc_password}

            cfg = None
            if args.provider == "imap" and args.host:
                cfg = {"imap_host": args.host, "imap_port": args.port, "use_ssl": not args.no_ssl}
            res = client.add_account(args.email, args.provider, creds, cfg)
            if output_json:
                print_json(res)
            else:
                print(f"Account added successfully: {res.get('id')} ({args.email})")

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
