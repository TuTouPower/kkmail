"""OAuth2 token refresh + Bearer HTTP transport for Graph.

credential_ref points at a JSON secret (via CredentialStore)::

    {
      "refresh_token": "...",
      "client_id": "...",
      "client_secret": "...",
      "token_uri": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
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
import math as _math
import re
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

# A187: provider responses are read with an explicit cap instead of being
# loaded into memory unbounded (MIME $value bodies vs JSON payloads).
MAX_JSON_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_MIME_RESPONSE_BYTES = 64 * 1024 * 1024


def _read_response_limited(resp: Any, limit: int) -> bytes:
    """Read at most ``limit + 1`` bytes; raise ProviderHttpError over the cap.

    Falls back to an unbounded read only for response objects whose
    ``read()`` takes no size argument (test doubles), still enforcing the cap.
    """
    try:
        raw = resp.read(limit + 1)
    except TypeError:
        raw = resp.read()
    if raw is None:
        return b""
    if isinstance(raw, str):
        raw = raw.encode("utf-8", errors="surrogateescape")
    if len(raw) > limit:
        raise ProviderHttpError(
            f"provider response exceeds the {limit}-byte size limit", status=None
        )
    return bytes(raw)

GRAPH_TOKEN_URI = "https://login.microsoftonline.com/common/oauth2/v2.0/token"

# Operator-supplied token_uri must match an allowlisted HTTPS host prefix (SSRF).
ALLOWED_TOKEN_URI_PREFIXES = (
    "https://login.microsoftonline.com/",
    "https://login.live.com/",
    "https://login.microsoft.com/",
)

TokenHttpFn = Callable[[str, str, dict[str, str], dict[str, str] | None], dict[str, Any]]
# (method, url, form_body, headers) -> JSON dict


class OAuthError(RuntimeError):
    """Token endpoint failure."""


_OAUTH_ERROR_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _sanitize_token_error_text(value: Any, *, limit: int) -> str:
    cleaned = _OAUTH_ERROR_CONTROL_CHARS.sub(" ", str(value or ""))
    return " ".join(cleaned.split())[:limit]


@dataclass
class OAuthTokenClient:
    """Refresh-token grant with optional persistence back to CredentialStore."""

    credential_ref: str
    store: CredentialStore
    provider: str = "graph"
    http_post: TokenHttpFn | None = None
    skew_seconds: float = 60.0
    timeout: float = 30.0
    # Connection-budget wiring (design §7): the refresh request acquires a
    # permit, completes, and releases it *before* any mail API connection
    # is opened by the caller — permits are never nested.
    permit_factory: Any = None
    traffic_class: Any = "foreground"
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
            uri = GRAPH_TOKEN_URI
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
        # Serialize refresh within this process so concurrent callers share
        # one token grant. The durable credential lock (A116) is held only
        # for the read/version-check and the final CAS persist — never
        # across the network POST, which can take tens of seconds and would
        # otherwise block every other process refreshing this credential.
        with self._refresh_lock:
            # Phase 1 (locked): reload + version check.
            with credential_edit(
                self.store,
                self.credential_ref,
                allow_readonly=True,
                readonly_cache=self._cached,
            ) as data:
                # Another process may have rotated it since our cache.
                self._cached = dict(data)
                if not force_refresh and self._access_valid(data):
                    return str(data["access_token"])
                snapshot = dict(data)
            refresh = snapshot.get("refresh_token")
            client_id = snapshot.get("client_id")
            client_secret = snapshot.get("client_secret")
            if not refresh or not client_id:
                raise OAuthError("credential JSON missing refresh_token or client_id")
            form = {
                "grant_type": "refresh_token",
                "refresh_token": str(refresh),
                "client_id": str(client_id),
            }
            if client_secret:
                form["client_secret"] = str(client_secret)
            if snapshot.get("scope"):
                form["scope"] = str(snapshot["scope"])
            uri = self.token_uri()
            if self.http_post is not None:
                post = self.http_post
            else:
                post = lambda m, u, f, h=None: default_urllib_token_post(m, u, f, h, timeout=self.timeout)
            # Phase 2 (unlocked): network refresh.
            try:
                # Acquire + complete + release the refresh permit inside
                # this scope; get_access_token returns before the caller
                # opens any mail API connection (no nested slot holding).
                from mail_core.providers.connection_slots import permit_scope

                with permit_scope(self.permit_factory, self.traffic_class):
                    resp = post("POST", uri, form, {"Content-Type": "application/x-www-form-urlencoded"})
            except ProviderHttpError as exc:
                raise OAuthError(f"token endpoint HTTP {exc.status}: {exc}") from exc
            if resp.get("error"):
                error_code = _sanitize_token_error_text(resp.get("error"), limit=80)
                error_description = _sanitize_token_error_text(resp.get("error_description"), limit=200)
                details = " ".join(part for part in (error_code, error_description) if part)
                raise OAuthError(f"token endpoint error: {details}")
            access = resp.get("access_token")
            if not access:
                raise OAuthError("token endpoint returned no access_token")
            # Phase 3 (locked): CAS persist keyed on the refresh_token
            # version we refreshed with. If another process rotated the
            # refresh_token while our POST was in flight, adopt the
            # already-persisted token instead of clobbering the rotation
            # with a grant issued against the superseded refresh_token.
            adopted: str | None = None
            with credential_edit(
                self.store,
                self.credential_ref,
                allow_readonly=True,
                readonly_cache=self._cached,
            ) as data:
                if data.get("refresh_token") != snapshot.get("refresh_token"):
                    if data.get("access_token"):
                        adopted = str(data["access_token"])
                        self._cached = dict(data)
                if adopted is None:
                    data["access_token"] = access
                    if resp.get("refresh_token"):
                        data["refresh_token"] = resp["refresh_token"]
                    # A169+A186: expires_in is optional, but expires_at must
                    # always be written. A missing value falls back to the
                    # IdP-conventional 3600s (otherwise _access_valid stays
                    # False and every API call forces a refresh); a malformed
                    # /non-finite value is treated as missing (A169) so it can
                    # never roll back persistence of the rotated refresh_token.
                    seconds = 3600.0
                    expires_in = resp.get("expires_in")
                    if expires_in is not None:
                        try:
                            parsed = float(expires_in)
                            if not _math.isfinite(parsed):
                                raise ValueError("non-finite expires_in")
                            seconds = parsed
                        except (TypeError, ValueError, OverflowError):
                            log.warning(
                                "oauth token response has unusable expires_in (type %s); "
                                "falling back to 3600s default",
                                type(expires_in).__name__,
                            )
                    data["expires_at"] = time.time() + seconds
                    self._cached = dict(data)
            if adopted is not None:
                return adopted
            return str(access)


def default_urllib_token_post(
    method: str,
    url: str,
    form: dict[str, str],
    headers: dict[str, str] | None = None,
    *,
    timeout: float = 30.0,
    permit_factory: Any = None,
    traffic_class: Any = "foreground",
) -> dict[str, Any]:
    """Stdlib token POST (used when no injectable http_post is given at runtime).

    When ``permit_factory`` is given the urlopen lifecycle holds one
    connection permit.  Callers going through :class:`OAuthTokenClient`
    must not pass a factory here as well — the client already scopes the
    whole refresh call, and permits are never nested.
    """
    import json
    import urllib.error
    import urllib.request

    from mail_core.providers.connection_slots import permit_scope

    body = urlencode(form).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method or "POST")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with permit_scope(permit_factory, traffic_class):
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — operator-configured token URI
                return json.loads(_read_response_limited(resp, MAX_JSON_RESPONSE_BYTES).decode("utf-8"))
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
                # Refresh credentials for the next attempt, but do not replay writes.
                token = self.token_client.get_access_token(force_refresh=True)
                if method.upper() not in {"GET", "HEAD"}:
                    raise AmbiguousOutcomeError(
                        f"{method.upper()} outcome ambiguous after HTTP 401; request not replayed"
                    ) from exc
                headers["Authorization"] = f"Bearer {token}"
                return self.inner(method, url, params, headers)
            raise






def _url_is_sync_cursor_endpoint(url: str) -> bool:
    """True for Graph delta URLs where 404/410 mean cursor invalid.

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
    permit_factory: Any = None,
    traffic_class: Any = "foreground",
) -> Any:
    """Generic JSON HTTP for Graph API calls (stdlib).

    Maps 404/410 → ``CursorInvalidError`` only for History / delta endpoints.
    Retries transient 503/504 errors and network/TLS dropouts for GET/HEAD only,
    with up to 3 retries (4 attempts total). Delays increase linearly by one
    second per retry unless a positive Retry-After header overrides the delay
    for 503/504 responses (capped at 10 seconds).
    Other methods are never replayed; ambiguous 5xx/transport outcomes raise
    ``AmbiguousOutcomeError``.

    Connection budget (design §7): when ``permit_factory`` is given, each
    attempt's urlopen lifecycle holds exactly one permit; the permit is
    released *before* any retry wait, never across sleeps.
    """
    import http.client
    import json
    import ssl
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    from mail_core.providers.connection_slots import permit_scope

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

        # The permit scope covers only the urlopen lifecycle.  HTTP and
        # transport failures are captured inside the scope (reading an
        # HTTPError body still needs the connection) and mapped *after*
        # the permit has been released, so retry waits hold no slot.
        http_outcome: tuple[int, str, dict] | None = None
        http_exc: BaseException | None = None
        transport_exc: BaseException | None = None
        with permit_scope(permit_factory, traffic_class):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                    # A187: bounded read. The pre-read cap follows the
                    # endpoint/content-type (MIME $value: 64MiB, JSON:
                    # 16MiB); JSON-looking bodies are re-checked against
                    # the JSON cap after the read as well.
                    ctype = resp.headers.get("Content-Type", "") if resp.headers else ""
                    is_mime = "$value" in url.lower() or "application/json" not in ctype
                    raw = _read_response_limited(
                        resp, MAX_MIME_RESPONSE_BYTES if is_mime else MAX_JSON_RESPONSE_BYTES
                    )
                    if not raw:
                        return {}
                    if "application/json" in ctype or raw[:1] in (b"{", b"["):
                        if len(raw) > MAX_JSON_RESPONSE_BYTES:
                            raise ProviderHttpError(
                                f"provider JSON response exceeds the "
                                f"{MAX_JSON_RESPONSE_BYTES}-byte size limit",
                                status=None,
                            )
                        return json.loads(raw.decode("utf-8"))
                    return {"raw_bytes": raw}
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                hdrs = {k: v for k, v in exc.headers.items()} if exc.headers else {}
                http_outcome = (exc.code, body, hdrs)
                http_exc = exc
            except (
                urllib.error.URLError,
                http.client.RemoteDisconnected,
                http.client.IncompleteRead,
                OSError,
                ssl.SSLEOFError,
            ) as exc:
                transport_exc = exc

        if http_outcome is not None:
            code, body, hdrs = http_outcome
            exc = http_exc
            if code == 429:
                raise RateLimitedError(body or str(exc), status=429, body=body, headers=hdrs) from exc
            if code in (404, 410) and _url_is_sync_cursor_endpoint(url):
                raise CursorInvalidError(body or str(exc), status=code, body=body, headers=hdrs) from exc
            if code >= 500 and not retryable:
                raise AmbiguousOutcomeError(
                    f"{method_upper} outcome ambiguous after HTTP {code}"
                ) from exc
            if code in (503, 504) and retryable and attempt <= max_retries:
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
            raise ProviderHttpError(body or str(exc), status=code, body=body, headers=hdrs) from exc

        if transport_exc is not None:
            exc = transport_exc
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
