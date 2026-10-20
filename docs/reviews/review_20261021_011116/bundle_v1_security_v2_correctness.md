# Bundle: V1 Security + V2 Correctness

- **Target**: TuTouPower/kkmail (public)
- **SHA**: b2956445574ebf171c1e73526421f0d46ccac3a3
- **Perspectives**: 1 Security, 2 Correctness
- **Filter**: none (zero-drop); confidence marked
- **Open-source privacy/history scan**: YES

---

## Perspective 1 — Security

### S1 [Critical][95] mail_core/api/mail.py:51-245, mail_core/api/sse.py:31-94, mail_core/api/app.py:33-41 — mail-core API has no authentication

**Evidence**
```python
# mail_core/api/app.py — CORS open to local SPA origins; no auth middleware
app.add_middleware(CORSMiddleware, allow_origins=[...], allow_credentials=True, ...)
app.include_router(mail_router)
# mail_core/api/mail.py — all routes unauthenticated
@router.get("/inbox")
@router.get("/messages/{message_id}")
@router.post("/messages/{message_id}/read")
@router.get("/attachments/{attachment_id}")
# mail_core/api/sse.py
@router.get("/events")  # streams mailbox events
```
Frontend `frontend/src/api/mailCore.ts` calls these with bare `fetch` / `EventSource` (no cookies, no API key).

**Attack**
Any client that can reach the mail-core port (compose binds `8000:8000` on `0.0.0.0`) can list inbox, read full message bodies, download attachments, flip read/flag, and subscribe to SSE. Combined with default DB password this is full mailbox compromise.

**Fix**
Add mandatory auth (shared secret, mTLS, or loopback-only bind + reverse-proxy auth). Do not expose `:8000` on host without auth. Align SPA to send credentials once Flask session / token gate exists.

---

### S2 [Critical][92] docker-compose.yml:8-18 — Docker socket mount + default credentials + auto-update

**Evidence**
```yaml
ports:
  - "5000:5000"
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
environment:
  - LOGIN_PASSWORD=[REDACTED]
  - SECRET_KEY=your-secret-key-here
  - DOCKER_UPDATE_ENABLED=true
```

**Attack**
1. Weak/default login → RCE via Docker API on the socket (create privileged container, mount host FS).
2. Even without login, if any path allows command/update after auth, socket = host root.
3. Fixed `SECRET_KEY` enables forging session cookies offline.

**Fix**
Never ship compose with docker.sock + weak secrets. Require strong `SECRET_KEY`/`LOGIN_PASSWORD` from env (as `docker-compose.react.yml` does for SECRET_KEY). Disable sock mount by default; isolate update agent.

---

### S3 [Critical][90] mail_core/blobs/crypto.py:59-61, docker-compose.mail-core.yml:49-52 — Deterministic / hardcoded blob encryption keys

**Evidence**
```python
if not keys:
    # Dev default — deterministic insecure key
    keys[1] = hashlib_sha256_bytes(b"kkmail-dev-blob-key-v1")
```
```yaml
MAIL_CORE_BLOB_KEY_V1: "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="  # 32 zero bytes
MAIL_CORE_BACKUP_KEY: "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
POSTGRES_PASSWORD: kkmail
```

**Attack**
Anyone who obtains ciphertext blobs (backup steal, volume copy, shared host) can decrypt with published keys. Silent fallback to known key means production misconfig still “works” while providing no confidentiality.

**Fix**
Fail closed if keys unset in non-dev. Generate random keys at install; never commit sample keys that decode to structured plaintext. Document rotation.

---

### S4 [Critical][88] .env.example:7-11 + LOGIN_PASSWORD default — Default admin password `[REDACTED]`

**Evidence**
```
SECRET_KEY=your-secret-key-here
LOGIN_PASSWORD=[REDACTED]
HOST=0.0.0.0
```
`outlook_web/segments/01_bootstrap.py:164`: `LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", "[REDACTED]")`

**Attack**
Internet-facing installs following docs are immediately takeover-able. `HOST=0.0.0.0` increases exposure.

**Fix**
Refuse start if password is default in production; force interactive/bootstrap secret generation (desktop already partially does for SECRET_KEY).

---

### S5 [High][90] outlook_web/segments/05_routes_refresh_mail.py:1606-1610 — State-changing GET `/api/accounts/refresh-all` (CSRF)

**Evidence**
```python
@app.route('/api/accounts/refresh-all', methods=['GET'])
@login_required
def api_refresh_all_accounts():
    return Response(stream_full_refresh_events(...), mimetype='text/event-stream')
```
Session cookie: `SameSite=Lax` → top-level GET navigations send cookie. CSRF cannot attach custom headers; GET needs none.

**Attack**
Malicious page: `<img src="https://victim:5000/api/accounts/refresh-all">` or navigation triggers mass token refresh / IMAP/Graph load as the logged-in user (availability + token churn + proxy abuse).

**Fix**
Use POST + CSRF for start; EventSource only for streaming a task id created via POST (pattern already used by `refresh-selected-stream`).

---

### S6 [High][88] outlook_web/segments/01_bootstrap.py:3267-3304 — Git skin install: unrestricted URL → SSRF / internal git

**Evidence**
```python
def normalize_git_skin_url(value: str) -> str:
    # only checks empty, length, leading '-', newlines
    return git_url
command = ['git', 'clone', '--depth', '1', normalized_url, str(repo_dir)]
subprocess.run(command, ...)
```
Route is `@login_required` but any authenticated admin (single password = all power) can clone `http://169.254.169.254/`, `git://internal`, file-like schemes depending on git build.

**Attack**
SSRF to cloud metadata / internal Git; large clone DoS; malicious skin content served to UI (stored XSS if skin HTML/JS executed — separate skin trust issue).

**Fix**
Allowlist `https://` hosts; block link-local/private IPs after DNS resolve; disable protocols other than https; optional signed skin registry.

---

### S7 [High][85] mail_core/providers/oauth.py:75-146 — Operator-controlled `token_uri` used with urlopen (SSRF)

**Evidence**
```python
def token_uri(self) -> str:
    if data.get("token_uri"):
        return str(data["token_uri"])
...
with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
```
Credential JSON comes from env/keyring; if an attacker can write `credential_ref` (compromised settings DB, malicious account import), refresh POSTs refresh_token + client_secret to attacker URL.

**Attack**
Credential exfiltration via fake token endpoint; SSRF to internal HTTP.

**Fix**
Allowlist token hosts (`oauth2.googleapis.com`, `login.microsoftonline.com`, `login.live.com`); reject user-supplied absolute URLs outside allowlist.

---

### S8 [High][85] mail_core/api/mail.py:240-245 — Content-Disposition header injection via attachment filename

**Evidence**
```python
headers = {
    "Content-Disposition": f'attachment; filename="{payload.filename}"',
}
```
Filename comes from mail metadata (attacker-controlled in received mail).

**Attack**
Filename containing `"` / CR/LF can split headers / inject `Content-Type` or XSS in some browsers/proxies. Flask path uses RFC 5987 `filename*=` encoding; mail-core does not.

**Fix**
Sanitize to basename; strip `\r\n\"`; use `filename*=UTF-8''...` like outlook_web helpers.

---

### S9 [High][82] outlook_web/segments/07_routes_oauth_settings_external.py:579-656 — `/api/settings` returns secrets in plaintext (+ bcrypt hash)

**Evidence**
```python
settings['external_api_key'] = get_external_api_key()  # full plaintext
settings['duckmail_api_key'] = get_duckmail_api_key()
settings['cloudflare_admin_password'] = get_cloudflare_admin_password()
settings['smtp_password'] = get_setting_decrypted(...)
settings['webdav_backup_password'] = get_setting_decrypted(...)
# login_password (bcrypt) never popped — only masked copy added
if 'login_password' in settings:
    settings['login_password_masked'] = ...
return jsonify({'success': True, 'settings': settings})
```

**Attack**
Any XSS or malicious extension with session steals API keys, SMTP/WebDAV passwords, and offline-crackable password hash. Single-password app → full credential dump.

**Fix**
Never return raw secrets; return `*_configured` + masked. `pop('login_password')`. Require re-auth to reveal.

---

### S10 [High][80] outlook_web/segments/03_mail_helpers.py:3326-3345 — API key accepted via query string

**Evidence**
```python
api_key = normalize_api_key(
    request.headers.get('X-API-Key')
    or request.args.get('api_key')
    or request.args.get('apikey')
)
```
Plus CORS `Access-Control-Allow-Origin: *` on `/api/external/*`.

**Attack**
Keys land in access logs, browser history, Referer. `*` CORS with credentialed? (key in query/header from any origin) enables cross-origin reads if key leaked to JS.

**Fix**
Header-only keys; redact logs; tighten CORS to explicit origins.

---

### S11 [High][78] outlook_web/segments/01_bootstrap.py:79-81,3365-3371 — Missing SESSION_COOKIE_SECURE; permanent sessions use datetime.max

**Evidence**
```python
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# no SESSION_COOKIE_SECURE
def get_expiration_time(...):
    if session.get(...) == 'permanent':
        return datetime.max.replace(tzinfo=timezone.utc)
```

**Attack**
On HTTPS reverse-proxy misconfig / mixed content, session cookie may go cleartext. Permanent cookie Max-Age extreme may confuse clients or persist forever after theft.

**Fix**
Set `SESSION_COOKIE_SECURE` when HTTPS detected; cap permanent duration (e.g. 1y) and rotate.

---

### S12 [High][75] outlook_web/segments/04_routes_groups_accounts.py:12-19 — Login rate limit trusts `X-Forwarded-For`

**Evidence**
```python
client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
client_ip = client_ip.split(',')[0].strip()
```
ProxyFix trusts 1 hop, but XFF leftmost is still client-spoofable if attacker hits app directly or extra hops exist.

**Attack**
Bypass lockout by rotating spoofed XFF; or lockout victims by forging their IP.

**Fix**
Use only `request.remote_addr` after trusted proxy count; ignore client-supplied XFF leftmost unless proxy is verified.

---

### S13 [High][78] docker-compose.mail-core.yml:18-19 — Postgres published on host `5433:5432` with password `kkmail`

**Evidence**
```yaml
ports:
  - "5433:5432"
POSTGRES_PASSWORD: kkmail
```

**Attack**
LAN/internet scanners get full mail DB (messages, credential_refs).

**Fix**
Do not publish DB port in prod; use strong password + internal network only.

---

### S14 [Medium][80] outlook_web/segments/01_bootstrap.py:141-156 — CSRF silently disabled if flask-wtf missing

**Evidence**
```python
except ImportError:
    CSRF_AVAILABLE = False
...
else:
    app.config['WTF_CSRF_ENABLED'] = False
```

**Attack**
Misbuilt image without flask-wtf → all state-changing POSTs CSRF-able.

**Fix**
Hard-fail startup in production if CSRF unavailable.

---

### S15 [Medium][75] outlook_web/segments/01_bootstrap.py:1083-1085 — Fixed PBKDF2 salt for Fernet key derivation

**Evidence**
```python
salt = b'outlook_email_encryption_salt_v1'
iterations=100000
```

**Attack**
Global salt + weak SECRET_KEY accelerates offline cracking of encrypted refresh tokens at rest. Architecture accepts SECRET_KEY strength dependency but fixed salt removes per-install diversity.

**Fix**
Random salt stored beside ciphertext; or use OS keyring for DEK.

---

### S16 [Medium][72] mail_core/blobs/crypto.py:82-85 — Non-magic payloads treated as plaintext

**Evidence**
```python
if len(payload) < 4 or payload[:4] != MAGIC:
    return payload, 0  # legacy identity stub
```

**Attack**
Integrity confusion: attacker replaces ciphertext with plaintext blob under same digest path if write access to store; unwrap succeeds without authentication tag.

**Fix**
Require encryption in prod; reject non-MAGIC unless explicit migration flag.

---

### S17 [Medium][70] outlook_web/segments/04_routes_groups_accounts.py:12-13,95-96 — Login endpoints CSRF-exempt

**Evidence**
`@csrf_exempt` on `/login` and `/api/extension/login`.

**Attack**
Login CSRF can fix session to attacker-chosen duration after victim types password on attacker page (less common) or confuse session state. More relevant: extension login returns one-time token — ensure token single-use (appears OK) but exempt increases CSRF surface.

**Fix**
Double-submit or SameSite strict for login; require Origin check.

---

### S18 [Medium][68] frontend/src/api/client.ts:78-81 — Unsafe methods proceed if CSRF token fetch fails

**Evidence**
```python
if (unsafe) {
  const token = await ensureCsrf()
  if (token) headers['X-CSRFToken'] = token  # silent skip if null
}
```

**Attack**
If `/api/csrf-token` fails transiently, write requests go without token → confusing failures; if server CSRF disabled (S14), client still “works” while unprotected.

**Fix**
Fail closed: abort unsafe requests when token missing.

---

### S19 [Medium][65] web_outlook_app.py:140, Dockerfile:36 — Default bind `0.0.0.0`

**Evidence**
`host = os.getenv("HOST", "127.0.0.1" if is_frozen() else "0.0.0.0")` and gunicorn `-b 0.0.0.0`.

**Attack**
Server deployments listen on all interfaces by default → wider attack surface for S2/S4.

**Fix**
Default to 127.0.0.1; document intentional public bind.

---

### S20 [Medium][70] outlook_web/segments/10_routes_email_shares.py:727-815 — Unauthenticated share token grants mailbox read

**Evidence**
Public routes `/share/email/<token>`, `/api/share/email/<token>/emails` without login. Token is `token_urlsafe(32)` (good entropy) and hashed at rest (good).

**Attack**
Token in URL leaks via Referer/logs; anyone with link reads mail until expiry. By design but high impact if links forwarded.

**Fix**
Optional auth gate; short TTL default; strip Referer; avoid token in query logs.

---

### S21 [Medium][60] mail_core/api/app.py:49-51 — `/ready` always ready (no DB/encryption checks)

**Evidence**
```python
@app.get("/ready")
def ready() -> dict[str, str]:
    return {"status": "ready"}
```
`security/defaults.py` documents encrypted volume requirement but never enforced.

**Attack**
Orchestrators route traffic before DB up; ops false sense of M5 encryption compliance.

**Fix**
Probe DB + require key env in ready; surface encryption checklist.

---

### S22 [Low][70] outlook_web/segments/01_bootstrap.py:145-146 — CSRF token never expires; SSL_STRICT false

**Evidence**
`WTF_CSRF_TIME_LIMIT = None`, `WTF_CSRF_SSL_STRICT = False`

**Fix**
Bound token lifetime; enable SSL_STRICT behind HTTPS.

---

### S23 [Low][55] mail_core/providers/imap.py:68-71 — `use_ssl` defaults False

**Evidence**
```python
use_ssl: bool = False
client = IMAP4_SSL(...) if self.use_ssl else IMAP4(...)
```

**Attack**
Misconfigured account → cleartext IMAP credentials on wire.

**Fix**
Default `use_ssl=True` for non-loopback hosts.

---

### S24 [Info][90] Open-source privacy / git history — real emails in commit metadata & history

**Evidence (git authors / history scan)**
- `***@***.com` (HEAD author)
- `[REDACTED_EMAIL]`, `[REDACTED_EMAIL]`, `[REDACTED_EMAIL]`, `[REDACTED_EMAIL]`, `[REDACTED_EMAIL]`, `[REDACTED_EMAIL]`, `[REDACTED_EMAIL]`, `[REDACTED_EMAIL]`, `[REDACTED_EMAIL]`
- Current tree: `desktop/package.json` uses `[REDACTED_EMAIL]` (safer)
- No live `.env` with production tokens found in current tree; `.env.example` has placeholders only
- `outlook_mail_reader.py` leaves empty EMAIL/REFRESH_TOKEN placeholders (good)

**Risk**
Contributor personal emails permanently in git history of a public repo.

**Fix**
Prefer GitHub noreply; `git filter-repo` only if owners want history purge (coordinate); avoid committing personal mail in tests (many `@outlook.com` fixtures look synthetic — OK).

---

### S25 [Info][50] mail_core/providers/oauth.py:86-87 — `expires_at is None` ⇒ access token treated forever valid

See Correctness C3 (also security: stale token use / confused refresh).

---

## Perspective 2 — Correctness

### C1 [High][92] outlook_mail_reader.py:41 — Uses `os.getenv` without importing `os`

**Evidence**
```python
IMAP_TIMEOUT = int(os.getenv("IMAP_TIMEOUT", "45"))
# file has no `import os`
```

**Bug**
`NameError` on import/run before any mail logic. Script is broken as shipped.

**Fix**
`import os` (and any other missing imports).

---

### C2 [High][85] outlook_web/segments/04_routes_groups_accounts.py:43-44 vs 01_bootstrap.py:3353-3355 — `/login` uses `verify_password` only; extension uses `verify_login_password`

**Evidence**
```python
# login()
if verify_password(password, stored_password):  # bcrypt-only
# verify_login_password handles plaintext fallback via compare_digest
```

**Bug**
If `login_password` setting missing and env `LOGIN_PASSWORD` plaintext is used, `/login` always fails while `/api/extension/login` succeeds (or vice versa depending on path). Inconsistent auth paths.

**Fix**
Both call `verify_login_password`.

---

### C3 [High][80] mail_core/providers/oauth.py:81-88 — Missing `expires_at` treated as non-expiring access token

**Evidence**
```python
if exp is None:
    return True
```

**Bug**
Cached access_token without expiry never refreshes → sudden 401 storms; with BearerTransport single retry may mask until refresh_token also fails.

**Fix**
If `expires_at` missing, force refresh or set short default TTL.

---

### C4 [High][78] mail_core/api/sse.py:48-92 — SSE generator closes DB session then long-polls; cursor gap logic uses local var rebinding carefully but `cursor` outer unused after assign in branch

**Evidence**
```python
if cursor > 0 and head - cursor > RESYNC_GAP:
    ...
    cursor_local = head
else:
    ...
    cursor_local = cursor
```
Then live loop. Correctness risk: `dispatcher.dispatch_once` on every keepalive from API process may duplicate worker side effects if both API and worker run (compose runs both).

**Bug**
Dual dispatcher tick (API SSE + worker) can race on outbox processing depending on `dispatch_once` idempotency.

**Fix**
Disable opportunistic dispatch when dedicated worker present (env flag).

---

### C5 [Medium][75] mail_core/blobs/crypto.py:59-65 — Active version `max(keys)` when env unset may not match intended v1 after multi-key load order

**Evidence**
```python
active = int(env.get(...) or max(keys))
```

**Bug**
If keys `{1,2}` loaded and env unset, active becomes 2 unexpectedly during rotation drills.

**Fix**
Require explicit `MAIL_CORE_BLOB_ACTIVE_VERSION` when multiple keys present.

---

### C6 [Medium][70] mail_core/backup/crypto.py:53-63 — `load_backup_keyring` rebuilds incompletely then merges

**Evidence**
Calls `load_backup_key` (which may raise) then re-parses JSON — redundant but OK; if only `MAIL_CORE_BACKUP_KEY` set, versions OK. Edge: `load_backup_key` already required keys; fine.

**Bug (subtle)**
None critical beyond duplication — mark lower: double JSON parse can disagree if env mutates mid-call (unlikely).

**Fix**
Single parse path.

---

### C7 [Medium][72] mail_core/api/mail.py:187-222 — POST read/flag: `body: ReadBody | None = None` then `want = True if body is None`

**Evidence**
Empty POST body → FastAPI may inject empty model or None depending on version; defaulting missing body to mark-read=True is surprising for clients sending `{}` vs no body.

**Bug**
Clients intending explicit unread may omit field and get mark-read True (`is_read: bool = True` default on model).

**Fix**
Require body; no implicit True.

---

### C8 [Medium][70] frontend/src/api/mailCore.ts:30-36 — Errors throw raw text; no credentials; EventSource no auth

**Evidence**
`fetch` without `credentials`; `new EventSource(`${base}/api/events`)`.

**Bug**
Even after auth is added server-side, current client cannot send cookies/tokens → broken integration. Correctness of cutover path.

**Fix**
Wire auth headers/cookies consistently with Flask session bridge.

---

### C9 [Medium][68] mail_core/providers/imap.py:116-119 — UID search `UID {start}:*` with empty result returns exhausted without distinguishing errors

**Evidence**
```python
if typ != "OK":
    return MetadataPage(items=(), next_cursor=cursor, exhausted=True)
```

**Bug**
Transient IMAP failures look like “folder done” → sync stops early, silent data loss until full rebuild.

**Fix**
Raise on non-OK; only exhaust on empty UID set with OK.

---

### C10 [Medium][65] outlook_web/segments/01_bootstrap.py:3368-3370 — `datetime.max` cookie expiry

**Evidence**
Permanent sessions set expiration to `datetime.max`.

**Bug**
Some browsers/libraries overflow or clamp unpredictably; session may appear permanent on server but drop on client.

**Fix**
Use finite far-future (e.g. 10 years).

---

### C11 [Medium][60] mail_core/db/session.py:20-26 — Module-level engine singleton ignores URL change after first init in same process without reset

**Evidence**
```python
if _engine is None or str(_engine.url) != resolved:
    _engine = create_engine(...)
```

**Bug**
URL equality via `str(_engine.url)` can mismatch password masking vs raw URL → recreate or fail to recreate in tests.

**Fix**
Compare normalized URL; provide `reset_engine()` for tests (may exist — verify callers).

---

### C12 [Low][70] outlook_web/segments/07_routes_oauth_settings_external.py:585-590 — “Masked” bcrypt still exposes first/last hash chars; full hash still in payload

**Bug**
Masking bcrypt is meaningless and leaks structure; full hash still returned (Security S9).

**Fix**
Drop both; only boolean configured.

---

### C13 [Low][60] mail_core/accounts/credentials.py:32-35 — `EnvCredentialStore.put_secret` mutates process env only

**Bug**
Refresh token rotation “persists” to env of one process; other workers/API don’t see update → split-brain tokens / revoke races.

**Fix**
Document single-process or persist to keyring/DB only.

---

### C14 [Low][55] web_outlook_app.py:47-48 — `exec(compile(...))` segment loader

**Bug**
All segments share one globals dict — import-order / name clash failures are runtime-only and hard to typecheck. Correctness/maintainability hazard (not remote RCE by itself).

**Fix**
Package modules with normal imports.

---

### C15 [Low][50] mail_core/api/app.py:19-20 — Listener `wait_started(timeout=5)` then continues even if not started?

**Evidence**
```python
listener.wait_started(timeout=5)
try:
    yield
```
If wait returns False on timeout, app still serves — SSE may miss events.

**Fix**
Fail startup or log+metric when listener not ready.

---

### C16 [Info][40] frontend/src/api/client.ts:96 — Treats `res.redirected` as 401

**Bug**
Any redirect (trailing slash, HTTP→HTTPS) clears session UX falsely.

**Fix**
Only treat 401; follow redirects carefully for API.

---

## Summary counts

| Severity | Security (V1) | Correctness (V2) | Total |
|----------|---------------|------------------|-------|
| Critical | 4 | 0 | 4 |
| High     | 9 | 4 | 13 |
| Medium   | 8 | 7 | 15 |
| Low      | 2 | 4 | 6 |
| Info     | 2 | 1 | 3 |
| **All**  | **25** | **16** | **41** |

**Combined unique finding rows**: 41 (S1–S25 + C1–C16).  
**Critical**: 4 · **High**: 13 · **Medium**: 15 · **Low**: 6 · **Info**: 3

### Highest-priority remediation order
1. Authenticate mail-core + don’t publish unauthenticated `:8000` / Postgres  
2. Remove docker.sock + default `[REDACTED]` / fixed SECRET_KEY from compose  
3. Fail closed on missing blob keys; rotate published sample keys  
4. Convert refresh-all to POST+CSRF; allowlist git/oauth URLs  
5. Stop returning secrets/hashes from `/api/settings`  
6. Fix `outlook_mail_reader.py` missing `import os`

