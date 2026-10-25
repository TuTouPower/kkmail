"""Tests for kkmail_cli.py (session cache security and HTTPS enforcement)."""

import importlib.util
import json
import os
import stat
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

CLI_PATH = Path(__file__).resolve().parents[2] / "docs" / "skills" / "kkmail-skill" / "scripts" / "kkmail_cli.py"
spec = importlib.util.spec_from_file_location("kkmail_cli", CLI_PATH)
kkmail_cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kkmail_cli)


def test_validate_target_url_loopback_allowed():
    """Loopback addresses must be allowed for both HTTP and HTTPS."""
    # HTTP loopback
    assert kkmail_cli.validate_target_url("http://127.0.0.1:37281").hostname == "127.0.0.1"
    assert kkmail_cli.validate_target_url("http://localhost:8000").hostname == "localhost"
    assert kkmail_cli.validate_target_url("http://[::1]:8000").hostname == "::1"
    assert kkmail_cli.validate_target_url("http://127.0.0.2:8080").hostname == "127.0.0.2"

    # HTTPS loopback
    assert kkmail_cli.validate_target_url("https://127.0.0.1:37281").hostname == "127.0.0.1"
    assert kkmail_cli.validate_target_url("https://localhost:8000").hostname == "localhost"


def test_validate_target_url_remote_https_allowed():
    """Remote hosts must be allowed if HTTPS."""
    assert kkmail_cli.validate_target_url("https://mail.example.com").hostname == "mail.example.com"
    assert kkmail_cli.validate_target_url("https://192.168.1.50:8443").hostname == "192.168.1.50"


def test_validate_target_url_remote_http_rejected():
    """Remote hosts over plain HTTP must be rejected."""
    with pytest.raises(ValueError, match="Insecure HTTP connection rejected"):
        kkmail_cli.validate_target_url("http://mail.example.com")

    with pytest.raises(ValueError, match="Insecure HTTP connection rejected"):
        kkmail_cli.validate_target_url("http://192.168.1.50:8000")

    with pytest.raises(ValueError, match="Insecure HTTP connection rejected"):
        kkmail_cli.validate_target_url("http://example.com/api")


def test_validate_target_url_unsupported_schemes():
    """Non-http/https schemes must be rejected."""
    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        kkmail_cli.validate_target_url("ftp://127.0.0.1:21")

    with pytest.raises(ValueError, match="Unsupported URL scheme"):
        kkmail_cli.validate_target_url("file:///etc/passwd")


def test_safe_redirect_handler_blocks_downgrade():
    """Redirecting to non-loopback HTTP must be blocked."""
    handler = kkmail_cli.SafeRedirectHandler("https://mail.example.com")
    req = urllib.request.Request("https://mail.example.com/api/test")

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        handler.redirect_request(req, None, 302, "Found", {}, "http://mail.example.com/api/test")
    assert "Redirect rejected by security policy" in str(exc_info.value)


def test_safe_redirect_handler_strips_credentials_on_cross_origin():
    """Redirecting to a different origin must strip sensitive headers."""
    handler = kkmail_cli.SafeRedirectHandler("https://mail.example.com")
    req = urllib.request.Request(
        "https://mail.example.com/api/inbox",
        headers={
            "Authorization": "Bearer secret-key",
            "Cookie": "kkmail_mc_session=xyz123",
            "X-CSRF-Token": "csrf-token-abc",
            "Accept": "application/json",
        },
    )

    new_req = handler.redirect_request(req, None, 302, "Found", {}, "https://other.example.com/api/inbox")
    assert new_req is not None

    headers_lower = {k.lower(): v for k, v in new_req.headers.items()}
    assert "authorization" not in headers_lower
    assert "cookie" not in headers_lower
    assert "x-csrf-token" not in headers_lower
    assert headers_lower.get("accept") == "application/json"


def test_safe_redirect_handler_blocks_login_payload_cross_origin():
    """Redirecting a login request with credentials to another origin must be blocked."""
    handler = kkmail_cli.SafeRedirectHandler("https://mail.example.com")
    req = urllib.request.Request(
        "https://mail.example.com/api/auth/login",
        data=b'{"password": "secret"}',
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        handler.redirect_request(req, None, 307, "Temporary Redirect", {}, "https://attacker.example.com/steal")
    assert "Redirect of login/credential payload" in str(exc_info.value)


def test_list_inbox_status_filters_are_sent_as_query_params(monkeypatch):
    client = kkmail_cli.KKMailClient(base_url="http://127.0.0.1:37281", api_key="test-key")
    requested_urls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"items": []}'

    def open_request(request, timeout):
        assert timeout == 30
        requested_urls.append(request.full_url)
        return Response()

    monkeypatch.setattr(client._opener, "open", open_request)

    client.list_inbox(limit=12, account_id="account-1", unread_only=True, flagged_only=True, cursor="next-page")

    assert len(requested_urls) == 1
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(requested_urls[0]).query)
    assert query == {
        "limit": ["12"],
        "account_id": ["account-1"],
        "is_read": ["false"],
        "is_flagged": ["true"],
        "cursor": ["next-page"],
    }


def test_health_bypasses_login_but_other_commands_still_require_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("KKMAIL_SESSION_CACHE", str(tmp_path / "session.json"))
    client = kkmail_cli.KKMailClient(base_url="http://127.0.0.1:37281", api_key="", password="")
    requested = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"status":"ok","service":"mail-core"}'

    def open_request(request, timeout):
        requested.append(request)
        assert timeout == 10
        return Response()

    monkeypatch.setattr(client._opener, "open", open_request)

    assert client.health() == {"status": "ok", "service": "mail-core"}
    assert len(requested) == 1
    assert requested[0].full_url == "http://127.0.0.1:37281/health"
    assert requested[0].get_header("Authorization") is None
    assert requested[0].get_header("Cookie") is None

    with pytest.raises(RuntimeError, match="Authentication failed"):
        client.stats()
    assert len(requested) == 1, "authenticated API methods must still pass through the login gate"


def test_format_read_status_preserves_unknown_state():
    assert kkmail_cli.format_read_status(True) == "✓"
    assert kkmail_cli.format_read_status(False) == "●"
    assert kkmail_cli.format_read_status(None) == "-"


@pytest.mark.parametrize("command", ["list", "search"])
def test_cli_list_and_search_render_all_read_states(command, monkeypatch, capsys):
    messages = [
        {"id": "read", "subject": "read subject", "from_address": "sender@example.com", "is_read": True},
        {"id": "unread", "subject": "unread subject", "from_address": "sender@example.com", "is_read": False},
        {"id": "unknown", "subject": "unknown subject", "from_address": "sender@example.com", "is_read": None},
    ]

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def list_inbox(self, **_kwargs):
            return {"items": messages, "next_cursor": None}

        def search(self, **_kwargs):
            return {"items": messages}

    monkeypatch.setattr(kkmail_cli, "KKMailClient", FakeClient)
    argv = ["kkmail_cli.py", "--api-key", "test-key", command]
    if command == "search":
        argv.append("subject")
    monkeypatch.setattr(kkmail_cli.sys, "argv", argv)

    kkmail_cli.main()

    rows = capsys.readouterr().out.splitlines()
    for message_id, symbol in (("read", "✓"), ("unread", "●"), ("unknown", "-")):
        assert any(line.startswith(f"  {symbol}   [{message_id}]") for line in rows)


def test_stats_renders_unknown_total_unread_as_dash(monkeypatch, capsys):
    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def stats(self):
            return {"total_unread": None, "accounts": []}

    monkeypatch.setattr(kkmail_cli, "KKMailClient", FakeClient)
    monkeypatch.setattr(kkmail_cli.sys, "argv", ["kkmail_cli.py", "--api-key", "test-key", "stats"])

    kkmail_cli.main()

    assert "Total unread messages: -" in capsys.readouterr().out


def test_json_option_before_subcommand_renders_json(monkeypatch, capsys):
    expected = {"total_unread": 4, "accounts": []}

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def stats(self):
            return expected

    monkeypatch.setattr(kkmail_cli, "KKMailClient", FakeClient)
    monkeypatch.setattr(kkmail_cli.sys, "argv", ["kkmail_cli.py", "--json", "stats"])

    kkmail_cli.main()

    assert json.loads(capsys.readouterr().out) == expected


def test_json_after_subcommand_is_rejected(monkeypatch, capsys):
    monkeypatch.setattr(kkmail_cli.sys, "argv", ["kkmail_cli.py", "stats", "--json"])

    with pytest.raises(SystemExit) as error:
        kkmail_cli.main()

    assert error.value.code == 2
    assert "unrecognized arguments: --json" in capsys.readouterr().err


def test_search_accepts_literal_json_option_after_separator(monkeypatch):
    queries = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def search(self, query, **_kwargs):
            queries.append(query)
            return {"items": []}

    monkeypatch.setattr(kkmail_cli, "KKMailClient", FakeClient)
    monkeypatch.setattr(kkmail_cli.sys, "argv", ["kkmail_cli.py", "search", "--", "--json"])

    kkmail_cli.main()

    assert queries == ["--json"]


def test_session_cache_permissions_default_mode(tmp_path, monkeypatch):
    """Default session cache directory must be 0700 and file must be 0600."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("KKMAIL_SESSION_CACHE", raising=False)

    client = kkmail_cli.KKMailClient(base_url="http://127.0.0.1:37281", password="test")
    client.cookie = "kkmail_mc_session=abc"
    client.csrf_token = "csrf123"
    client._save_session_cache()

    cache_dir = fake_home / ".cache" / "kkmail"
    cache_file = cache_dir / "session.json"

    assert cache_dir.is_dir()
    assert cache_file.is_file()

    # Verify directory permissions: 0700
    dir_mode = stat.S_IMODE(cache_dir.stat().st_mode)
    assert dir_mode == 0o700

    # Verify file permissions: 0600
    file_mode = stat.S_IMODE(cache_file.stat().st_mode)
    assert file_mode == 0o600

    # Verify load
    client2 = kkmail_cli.KKMailClient(base_url="http://127.0.0.1:37281", password="test")
    assert client2.cookie == "kkmail_mc_session=abc"
    assert client2.csrf_token == "csrf123"


def test_session_cache_custom_path_does_not_modify_parent_permissions(tmp_path, monkeypatch):
    """Custom KKMAIL_SESSION_CACHE must not chmod user's shared parent directory."""
    parent_dir = tmp_path / "shared"
    parent_dir.mkdir(mode=0o755)
    custom_cache = parent_dir / "my_session.json"
    monkeypatch.setenv("KKMAIL_SESSION_CACHE", str(custom_cache))

    client = kkmail_cli.KKMailClient(base_url="http://127.0.0.1:37281", password="test")
    client.cookie = "kkmail_mc_session=custom"
    client.csrf_token = "csrf-custom"
    client._save_session_cache()

    # Parent directory permissions must remain untouched (0755)
    parent_mode = stat.S_IMODE(parent_dir.stat().st_mode)
    assert parent_mode == 0o755

    # But session file must be 0600
    file_mode = stat.S_IMODE(custom_cache.stat().st_mode)
    assert file_mode == 0o600


def test_session_cache_refuses_symlink_file(tmp_path, monkeypatch):
    """Session cache must refuse to write to or read from a symlink."""
    fake_home = tmp_path / "home"
    cache_dir = fake_home / ".cache" / "kkmail"
    cache_dir.mkdir(parents=True)
    target = tmp_path / "sensitive.txt"
    target.write_text("sensitive data", encoding="utf-8")

    symlink_file = cache_dir / "session.json"
    symlink_file.symlink_to(target)

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("KKMAIL_SESSION_CACHE", raising=False)

    client = kkmail_cli.KKMailClient(base_url="http://127.0.0.1:37281", password="test")
    # Must refuse to read symlink
    assert client.cookie is None

    # Must refuse to overwrite symlink
    client.cookie = "malicious_session"
    client._save_session_cache()
    # Target content must remain unchanged
    assert target.read_text(encoding="utf-8") == "sensitive data"


def test_legacy_cache_migration(tmp_path, monkeypatch):
    """Legacy ~/.cache/kkmail_agent_session.json must be migrated and removed."""
    fake_home = tmp_path / "home"
    legacy_dir = fake_home / ".cache"
    legacy_dir.mkdir(parents=True)
    legacy_file = legacy_dir / "kkmail_agent_session.json"
    legacy_file.write_text(
        json.dumps({
            "base_url": "http://127.0.0.1:37281",
            "cookie": "legacy_cookie_val",
            "csrf_token": "legacy_csrf_val",
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("KKMAIL_SESSION_CACHE", raising=False)

    client = kkmail_cli.KKMailClient(base_url="http://127.0.0.1:37281", password="test")
    assert client.cookie == "legacy_cookie_val"
    assert client.csrf_token == "legacy_csrf_val"

    # Legacy file must be deleted
    assert not legacy_file.exists()

    # New cache file must exist with 0600
    new_cache = fake_home / ".cache" / "kkmail" / "session.json"
    assert new_cache.is_file()
    assert stat.S_IMODE(new_cache.stat().st_mode) == 0o600


def test_session_cache_corrects_existing_lax_permissions(tmp_path, monkeypatch):
    """Loading existing session file with lax permissions (0644) must tighten it to 0600."""
    fake_home = tmp_path / "home"
    cache_dir = fake_home / ".cache" / "kkmail"
    cache_dir.mkdir(parents=True, mode=0o755)
    cache_file = cache_dir / "session.json"
    cache_file.write_text(
        json.dumps({
            "base_url": "http://127.0.0.1:37281",
            "cookie": "test_cookie",
            "csrf_token": "test_csrf",
        }),
        encoding="utf-8",
    )
    cache_file.chmod(0o644)

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("KKMAIL_SESSION_CACHE", raising=False)

    client = kkmail_cli.KKMailClient(base_url="http://127.0.0.1:37281", password="test")
    assert client.cookie == "test_cookie"
    assert stat.S_IMODE(cache_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(cache_dir.stat().st_mode) == 0o700


def test_session_cache_refuses_symlink_directory(tmp_path, monkeypatch):
    """If default cache directory is a symlink, client must refuse to use it."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    real_dir = tmp_path / "somewhere_else"
    real_dir.mkdir()

    symlink_dir = fake_home / ".cache"
    symlink_dir.mkdir()
    (symlink_dir / "kkmail").symlink_to(real_dir)

    monkeypatch.setattr(Path, "home", lambda: fake_home)
    monkeypatch.delenv("KKMAIL_SESSION_CACHE", raising=False)

    client = kkmail_cli.KKMailClient(base_url="http://127.0.0.1:37281", password="test")
    client.cookie = "cookie_data"
    client._save_session_cache()

    # Nothing should be written to real_dir
    assert list(real_dir.iterdir()) == []


def test_client_preserves_password_and_api_key_whitespace():
    """Credential values are opaque; surrounding spaces may be intentional."""
    client = kkmail_cli.KKMailClient(
        base_url="http://127.0.0.1:37281",
        api_key="  key with spaces  ",
        password="  password with spaces  ",
    )

    assert client.api_key == "  key with spaces  "
    assert client.password == "  password with spaces  "
