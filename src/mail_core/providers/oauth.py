"""OAuth2 token refresh + Bearer HTTP transport for Gmail / Graph.

credential_ref points at a JSON secret (via CredentialStore)::

    {
      "refresh_token": "...",
      "client_id": "...",
      "client_secret": "...",
      "token_uri": "https://oauth2.googleapis.com/token",
      "access_token": "...",          # optional cache
      "expires_at": 1710000000.0,    # unix seconds, optional
      "scope": "..."                 # optional
    }

Graph commonly uses::

    "token_uri": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

No send/SMTP. Access tokens are never logged.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urlencode

from mail_core.accounts.credentials import (
    CredentialStore,
    load_json_secret,
    credential_edit,
)
from mail_core.providers.http import AmbiguousOutcomeError, CursorInvalidError, ProviderHttpError, RateLimitedError

log = logging.getLogger("mail_core.providers.oauth")

GMAIL_TOKEN_URI = "https://oauth2.googleapis.com/token"
GRAPH_TOKEN_URI = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

# Operator-supplied token_uri must match an allowlisted HTTPS host prefix (SSRF).
ALLOWED_TOKEN_URI_PREFIXES = (
    "https://oauth2.googleapis.com/",
    "https://www.googleapis.com/oauth2/",
    "https://login.microsoftonline.com/",
    "https://login.live.com/",
    "https://login.microsoft.com/",
)

TokenHttpFn = Callable[[str, str, dict[str, str], dict[str, str] | None], dict[str, Any]]
# (method, url, form_body, headers) -> JSON dict


class OAuthError(RuntimeError):
    """Token endpoint failure."""


@dataclass
class OAuthTokenClient:
    """Refresh-token grant with optional persistence back to CredentialStore."""

    credential_ref: str
    store: CredentialStore
    provider: str = "gmail"  # gmail | graph
    http_post: TokenHttpFn | None = None
    skew_seconds: float = 60.0
    timeout: float = 30.0
    _cached: dict[str, Any] = field(default_factory=dict, repr=False)
    _refresh_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def _load(self) -> dict[str, Any]:
        if self._cached:
            return self._cached
        data = load_json_secret(self.store, self.credential_ref)
        self._cached = dict(data)
        return self._cached

    def token_uri(self) -> str:
        data = self._load()
        if data.get("token_uri"):
            uri = str(data["token_uri"]).strip()
        else:
            uri = GMAIL_TOKEN_URI if self.provider == "gmail" else GRAPH_TOKEN_URI
        if not any(uri.startswith(p) for p in ALLOWED_TOKEN_URI_PREFIXES):
            raise OAuthError(
                "token_uri is not on the HTTPS provider allowlist "
                f"(got host path starting {uri[:48]!r}…)"
            )
        return uri

    def _access_valid(self, data: dict[str, Any]) -> bool:
        token = data.get("access_token")
        exp = data.get("expires_at")
        if not token:
            return False
        # Missing expires_at must NOT mean forever-valid — force refresh.
        if exp is None:
            return False
        try:
            return float(exp) > time.time() + self.skew_seconds
        except (TypeError, ValueError):
            return False

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        # Serialize refresh so concurrent callers share one token grant.
        with self._refresh_lock, credential_edit(
            self.store,
            self.credential_ref,
            allow_readonly=True,
            readonly_cache=self._cached,
        ) as data:
            # Reload under the durable row lock; another process may have rotated it.
            self._cached = dict(data)
            if not force_refresh and self._access_valid(data):
                return str(data["access_token"])
            refresh = data.get("refresh_token")
            client_id = data.get("client_id")
            client_secret = data.get("client_secret")
            if not refresh or not client_id:
                raise OAuthError("credential JSON missing refresh_token or client_id")
            form = {
                "grant_type": "refresh_token",
                "refresh_token": str(refresh),
                "client_id": str(client_id),
            }
            if client_secret:
                form["client_secret"] = str(client_secret)
            if data.get("scope"):
                form["scope"] = str(data["scope"])
            uri = self.token_uri()
            if self.http_post is not None:
                post = self.http_post
            else:
                post = lambda m, u, f, h=None: default_urllib_token_post(m, u, f, h, timeout=self.timeout)
            try:
                resp = post("POST", uri, form, {"Content-Type": "application/x-www-form-urlencoded"})
            except ProviderHttpError as exc:
                raise OAuthError(f"token endpoint HTTP {exc.status}: {exc}") from exc
            if resp.get("error"):
                raise OAuthError(f"token endpoint error: {resp.get('error')} {resp.get('error_description')}")
            access = resp.get("access_token")
            if not access:
                raise OAuthError("token endpoint returned no access_token")
            data["access_token"] = access
            if resp.get("refresh_token"):
                data["refresh_token"] = resp["refresh_token"]
            expires_in = resp.get("expires_in")
            if expires_in is not None:
                data["expires_at"] = time.time() + float(expires_in)
            self._cached = dict(data)
            return str(access)


def default_urllib_token_post(
    method: str,
    url: str,
    form: dict[str, str],
    headers: dict[str, str] | None = None,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Stdlib token POST (used when no injectable http_post is given at runtime)."""
    import json
    import urllib.error
    import urllib.request

    body = urlencode(form).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method or "POST")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — operator-configured token URI
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise ProviderHttpError(raw or str(exc), status=exc.code, body=raw, headers=dict(exc.headers or {})) from exc
    except urllib.error.URLError as exc:
        raise ProviderHttpError(f"token transport error: {exc.reason}", status=None) from exc


@dataclass
class BearerTransport:
    """Wraps an underlying JSON transport with OAuth Bearer + status mapping."""

    token_client: OAuthTokenClient
    inner: Callable[[str, str, dict[str, Any] | None, dict[str, str] | None], Any]
    # inner(method, path, params, headers) -> dict | raises ProviderHttpError
    base_url: str = ""

    def __call__(self, method: str, path: str, params: dict[str, Any] | None = None) -> Any:
        if path.startswith("http://") or path.startswith("https://"):
            url = path
            if self.base_url:
                from urllib.parse import urlparse

                base_parts = urlparse(self.base_url)
                url_parts = urlparse(url)
                if (url_parts.scheme.lower(), url_parts.netloc.lower()) != (
                    base_parts.scheme.lower(),
                    base_parts.netloc.lower(),
                ):
                    raise OAuthError(
                        f"cross-origin Bearer request denied: target origin {url_parts.scheme}://{url_parts.netloc} "
                        f"does not match base origin {base_parts.scheme}://{base_parts.netloc}"
                    )
        else:
            url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        token = self.token_client.get_access_token()
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        try:
            return self.inner(method, url, params, headers)
        except RateLimitedError:
            raise
        except CursorInvalidError:
            raise
        except ProviderHttpError as exc:
            if exc.status == 401:
                # One forced refresh then retry
                token = self.token_client.get_access_token(force_refresh=True)
                headers["Authorization"] = f"Bearer {token}"
                return self.inner(method, url, params, headers)
            raise






def _url_is_sync_cursor_endpoint(url: str) -> bool:
    """True for Gmail History / Graph delta URLs where 404/410 mean cursor invalid.

    Labels, message get, MIME ``$value``, send, etc. must *not* map to
    ``CursorInvalidError`` — those are ordinary resource misses.
    """
    u = (url or "").lower()
    if "/history" in u:
        return True
    if "messages/delta" in u or "/delta?" in u or u.rstrip("/").endswith("/delta"):
        return True
    if "deltatoken=" in u:
        return True
    return False


def urllib_json_request(
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    *,
    timeout: float = 60.0,
    _sleep_fn: Any = None,
) -> Any:
    """Generic JSON HTTP for Gmail/Graph API calls (stdlib).

    Maps 404/410 → ``CursorInvalidError`` only for History / delta endpoints.
    Retries transient 503/504 errors and network/TLS dropouts for GET/HEAD only.
    Other methods are never replayed; ambiguous 5xx/transport outcomes raise
    ``AmbiguousOutcomeError``.
    """
    import http.client
    import json
    import ssl
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    sleep = _sleep_fn or time.sleep
    max_retries = 3
    method_upper = method.upper()
    retryable = method_upper in {"GET", "HEAD"}

    for attempt in range(1, max_retries + 2):
        if params:
            # For GET, attach query; for POST with dict body use JSON
            if method_upper == "GET":
                q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
                target_url = f"{url}?{q}" if q else url
                data = None
            else:
                target_url = url
                data = json.dumps(params).encode("utf-8")
        else:
            target_url = url
            data = None

        req = urllib.request.Request(target_url, data=data, method=method_upper)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        if data is not None and method_upper != "GET":
            req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                raw = resp.read()
                if not raw:
                    return {}
                ctype = resp.headers.get("Content-Type", "")
                if "application/json" in ctype or raw[:1] in (b"{", b"["):
                    return json.loads(raw.decode("utf-8"))
                return {"raw_bytes": raw}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            hdrs = {k: v for k, v in exc.headers.items()} if exc.headers else {}
            if exc.code == 429:
                raise RateLimitedError(body or str(exc), status=429, body=body, headers=hdrs) from exc
            if exc.code in (404, 410) and _url_is_sync_cursor_endpoint(url):
                raise CursorInvalidError(body or str(exc), status=exc.code, body=body, headers=hdrs) from exc
            if exc.code >= 500 and not retryable:
                raise AmbiguousOutcomeError(
                    f"{method_upper} outcome ambiguous after HTTP {exc.code}"
                ) from exc
            if exc.code in (503, 504) and retryable and attempt <= max_retries:
                delay = attempt * 1.0
                if hdrs.get("Retry-After"):
                    try:
                        ra = float(hdrs["Retry-After"])
                        if ra > 0:
                            delay = min(ra, 10.0)
                    except (ValueError, TypeError):
                        pass
                sleep(delay)
                continue
            raise ProviderHttpError(body or str(exc), status=exc.code, body=body, headers=hdrs) from exc
        except (
            urllib.error.URLError,
            http.client.RemoteDisconnected,
            http.client.IncompleteRead,
            OSError,
            ssl.SSLEOFError,
        ) as exc:
            reason = getattr(exc, "reason", str(exc))
            reason_str = str(reason).lower()
            if "certificate_verify_failed" in reason_str:
                raise ProviderHttpError(f"transport error: {reason}", status=None) from exc
            if not retryable:
                raise AmbiguousOutcomeError(
                    f"{method_upper} outcome ambiguous after transport error ({type(exc).__name__})"
                ) from exc
            if attempt <= max_retries:
                delay = min(attempt * 1.0, 10.0)
                sleep(delay)
                continue
            raise ProviderHttpError(f"transport error: {reason}", status=None) from exc
