> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

> [!NOTE]
> **勘误注记（A392 / R3-H02）**：本文件实际收录 124 条 finding（Critical 4 / High 36 / Medium 49 / Low 24 / Info 11，逐行复点），与同包 `review_intensive.md` 自称的 118 条（其分布为 Medium 45 / Low 22）不一致；差异成因是该统计为旧会话残留、未按本文件最终清单重生成。本文件条目数引用以实数 124 为准，118 勿再引用。正文未改，此注记即为勘误。

# Machine-readable findings (post cross-validation)

- Target: TuTouPower/kkmail @ b2956445574ebf171c1e73526421f0d46ccac3a3

- Critical/High conf from bundle_cross_validation.md NewConf; Medium/Low/Info original.

- Deduped: reclaim_stale (V4+V6), /ready (S21+V3+V6), optional POST body (C7+V3), Content-Disposition Medium subsumed by S8, OpenSpec TBD×2, Flagged docs×2.

- CHALLENGED Highs retained with lowered conf: C2, C4, V6-R5.

- [Critical][97] mail_core/api/app.py:33 — mail-core API/SSE unauthenticated; compose publishes :8000 on 0.0.0.0

- [Critical][92] docker-compose.yml:8 — docker.sock mount + default \*\*\*/SECRET_KEY + DOCKER_UPDATE_ENABLED

- [Critical][92] mail_core/blobs/crypto.py:59 — deterministic/hardcoded blob encryption keys (dev fallback + compose samples)

- [Critical][90] .env.example:7 — default LOGIN_PASSWORD=\*\*\* (env + bootstrap); CONNECT S2

- [High][98] web_outlook_app.py:23 — Flask god-namespace via exec of 12 segments (~26.6k LOC shared globals)

- [High][97] .github/workflows/tests.yml:20 — CI runs only 2 pytest modules; omits mail_core and full suite

- [High][97] frontend/src/store/mailStore.ts:8 — Flask accountId number passed as mail-core account_id UUID (422)

- [High][95] .github/workflows/frontend.yml:24 — frontend CI only npm build; skips vitest/lint/tsc

- [High][95] mail_core/providers/oauth.py:39 — triple OAuth/IMAP/Graph duplication (segments + outlook_mail_reader + mail_core)

- [High][95] mail_core/sync/jobs.py:76 — fail_job permanently FAILED; attempts unused for backoff requeue

- [High][95] mail_core/sync/metadata.py:81 — \_recompute_folder_stats loads entire folder into ORM per page/mutation

- [High][95] outlook_mail_reader.py:41 — uses os.getenv without import os (NameError)

- [High][95] AGENTS.md:1 — Trellis instructions point at missing .trellis/ and .agents/

- [High][92] frontend/src/api/mailCore.ts:81 — mailCoreToMailItem maps accountEmail to UUID; drops numeric accountId

- [High][92] mail_core/api/mail.py:33 — MessageOut omits is_flagged while flag mutation exists

- [High][92] tests/test_outlook_graph_send_mail_frontend.py:7 — primary UI contracts assert legacy templates/static, not React SPA

- [High][90] README.md:69 — README↔docs/deployment.md dual deployment authority / non-minimal entry

- [High][90] mail_core/api/mail.py:12 — API bypasses application for blobs/search; SSE reaches storage ORM

- [High][90] mail_core/mail/application/mutations.py:14 — application layer imports sync internals and private \_recompute_folder_stats

- [High][90] mail_core/mail/storage/models.py:109 — message_locations lacks folder_id-leading index for inbox path

- [High][90] mail_core/sync/jobs.py:82 — reclaim_stale_claims unused by worker (V4+V6); CLAIMED jobs stick forever

- [High][88] mail_core/mail/application/remote_ops.py:15 — remote-op idempotency_key unique but enqueue does not upsert → IntegrityError

- [High][88] mail_core/mail/storage/models.py:278 — worker_jobs has no idempotency/dedup key → duplicate sync storms

- [High][88] mail_core/sync/engine.py:246 — local_remote_ids_for_folder unbounded SELECT of all remote_ids

- [High][88] outlook_web/segments/01_bootstrap.py:3267 — git skin install unrestricted URL → SSRF / internal git

- [High][88] outlook_web/segments/05_routes_refresh_mail.py:1606 — state-changing GET /api/accounts/refresh-all (CSRF via top-level nav)

- [High][88] outlook_web/segments/07_routes_oauth_settings_external.py:579 — /api/settings returns secrets in plaintext (+ bcrypt hash unpurged)

- [High][85] frontend/src/api/mailCore.ts:30 — mail-core frontend client has no request timeout (Flask path does)

- [High][85] mail_core/api/mail.py:240 — Content-Disposition header injection via attachment filename

- [High][85] mail_core/providers/imap.py:70 — IMAP provider has no socket/connect timeout

- [High][85] mail_core/providers/oauth.py:75 — operator-controlled token_uri used with urlopen (SSRF/exfil)

- [High][85] outlook_mail_reader.py:123 — orphan script prints refresh-token prefix + raw token error bodies (CONNECT C1)

- [High][82] mail_core/providers/oauth.py:81 — missing expires_at treated as non-expiring access token

- [High][82] outlook_web/segments/03_mail_helpers.py:3326 — API key accepted via query string; CORS * on /api/external

- [High][82] outlook_web/segments/04_routes_groups_accounts.py:12 — login rate limit trusts X-Forwarded-For leftmost (bypasses ProxyFix)

- [High][80] docker-compose.mail-core.yml:18 — Postgres published on host 5433:5432 with password \*\*\*

- [High][78] outlook_web/segments/01_bootstrap.py:79 — missing SESSION_COOKIE_SECURE; permanent sessions use datetime.max

- [High][72] outlook_web/segments/03_mail_helpers.py:295 — request_with_proxy_failover lacks default timeout (callers usually pass; CHALLENGED)

- [High][70] outlook_web/segments/04_routes_groups_accounts.py:43 — /login verify_password vs extension verify_login_password (CHALLENGED: init hashes)

- [High][65] mail_core/api/sse.py:48 — SSE/listener dual dispatch_once race (CHALLENGED: mark_dispatched limits impact)

- [Medium][90] tests/mail_core/ — mail_core tests skip without MAIL_CORE_DATABASE_URL; CI template not under .github

- [Medium][88] docs/mail-core-cutover.md:1 — dual Flask+mail_core stacks without shared domain boundary

- [Medium][88] docs/mail-core-status.md:9 — mail-core-status.md retains agent/session tone

- [Medium][88] mail_core/api/mail.py:109 — search API returns only IDs; no hydrate/cursor/total contract

- [Medium][88] mail_core/search/index.py:58 — subject ILIKE/similarity without subject trigram index

- [Medium][85] README.md:69 — weak default \*\*\* as documentation example default

- [Medium][85] mail_core/api/mail.py:87 — most mail-core routes lack response_model; bare-string errors

- [Medium][85] mail_core/sync/engine.py:81 — sync folder discovery N+1 SELECT per remote folder

- [Medium][85] openspec/specs/ — OpenSpec Purpose TBD placeholders (cloudflare-\*/email-address-fallback)

- [Medium][85] static/js/index/ — dual UIs (legacy static/js + React frontend) both live

- [Medium][82] mail_core/db/session.py:26 — engine pool untuned (pool_pre_ping only)

- [Medium][82] openspec/specs/group-tree-ui/spec.md:13 — group-tree-ui spec vs flat React Sidebar (half-implemented on main UI)

- [Medium][80] docs/known-limitations.md:5 — Flagged local-only docs conflict with mail-core flag API

- [Medium][80] mail_core/api/mail.py:187 — optional POST body defaults mark-read/flag to True (C7+V3)

- [Medium][80] mail_core/blobs/store.py:96 — attachment download loads full blob into memory

- [Medium][80] outlook_web/segments/01_bootstrap.py:141 — CSRF silently disabled if flask-wtf missing

- [Medium][80] outlook_web/segments/05_routes_refresh_mail.py:1 — oversized god files (routes/helpers/tests ≫ 800–1000 LOC)

- [Medium][78] frontend/src/ — no E2E; SPA components almost untested

- [Medium][78] mail_core/api/app.py:49 — /ready always ready without DB/listener probe (S21+V3+V6 dedup)

- [Medium][78] mail_core/sync/jobs.py:94 — reclaim_stale_claims has no LIMIT when used

- [Medium][78] web_outlook_app.py:84 — desktop shutdown swallows Exception with pass

- [Medium][75] DESIGN.md:1 — DESIGN.md is UI tokens; system architecture lives in docs/mail-core-architecture.md

- [Medium][75] frontend/src/api/client.ts:160 — dual list schemas Flask vs mail-core easy silent empty fields

- [Medium][75] frontend/src/api/queries.ts:94 — all-inbox fans out up to 8 parallel Flask fetches

- [Medium][75] outlook_web/segments/01_bootstrap.py:1083 — fixed PBKDF2 salt for Fernet key derivation

- [Medium][75] outlook_web/segments/03_mail_helpers.py:1 — ~47 except Exception: pass (+ many bare Exception) in segments

- [Medium][72] mail_core/api/sse.py:74 — SSE keepalive triggers dispatch_once every 15s per connection

- [Medium][72] mail_core/blobs/crypto.py:82 — non-MAGIC payloads treated as plaintext

- [Medium][72] mail_core/worker/handlers.py:137 — fail_job last_error may store provider HTTP bodies

- [Medium][70] frontend/src/api/mailCore.ts:30 — mailCore errors throw raw text; no credentials; EventSource no auth

- [Medium][70] frontend/src/lib/mailCoreFlag.test.ts:10 — weak boolean typeof assert; conditional empty pass

- [Medium][70] mail_core/api/mail.py:54 — cursor query vs next_cursor key naming undocumented/untyped

- [Medium][70] mail_core/backup/crypto.py:53 — load_backup_keyring rebuilds/parses redundantly

- [Medium][70] mail_core/sync/metadata.py:108 — metadata apply write amplification (per-message search/thread/outbox)

- [Medium][70] outlook_web/segments/01_bootstrap.py:1161 — mail_core lacks Flask-equivalent sanitize_error_details redaction

- [Medium][70] outlook_web/segments/04_routes_groups_accounts.py:12 — login endpoints CSRF-exempt

- [Medium][70] outlook_web/segments/10_routes_email_shares.py:727 — unauthenticated share token grants mailbox read (by design, high impact)

- [Medium][70] web_outlook_app.py:130 — run_windows_desktop thin alias of run_desktop_app

- [Medium][68] frontend/src/api/client.ts:78 — unsafe methods proceed if CSRF token fetch fails

- [Medium][68] mail_core/providers/imap.py:116 — IMAP non-OK search treated as exhausted (silent sync stop)

- [Medium][68] outlook_web/segments/02_groups_accounts.py:1013 — resolve_account_record silent decrypt failure

- [Medium][65] mail_core/sync/engine.py:61 — folder discovery lacks RateLimitedError handling (permanent fail)

- [Medium][65] outlook_web/segments/01_bootstrap.py:3368 — datetime.max cookie expiry unpredictability (CONNECT S11)

- [Medium][65] tests/ — CSRF tests skipUnless(CSRF_AVAILABLE) — silent skip if flask-wtf missing

- [Medium][65] web_outlook_app.py:140 — default bind 0.0.0.0 (non-frozen)

- [Medium][60] mail_core/db/session.py:20 — module-level engine singleton URL compare/masking edge cases

- [Medium][60] mail_core/mail/domain/archive.py:1 — domain archive FSM present but application mutations ignore archive

- [Medium][55] mail_core/realtime/listener.py:88 — NOTIFY payload / reconnect may log PII at debug/exception

- [Medium][50] docs/mail-core-cutover.md:1 — feature-flag cutover multiplies Flask/Vite switches

- [Low][75] mail_core/api/mail.py:121 — duplicate body endpoints GET /messages/{id} and /body

- [Low][70] mail_core/api/mail.py:46 — PageOut.next_cursor dict|None untyped

- [Low][70] mail_core/mail/application/__init__.py:1 — empty application/api __init__ public exports incomplete

- [Low][70] outlook_web/segments/01_bootstrap.py:145 — CSRF token never expires; WTF_CSRF_SSL_STRICT false

- [Low][70] outlook_web/segments/07_routes_oauth_settings_external.py:585 — masked bcrypt still exposes structure; full hash in payload (see S9)

- [Low][65] mail_core/api/app.py:44 — health returns version but no alembic revision

- [Low][65] web_outlook_app.py:1 — outlook\_\* naming while product is kkmail/multi-provider

- [Low][60] docs/api.md:1 — docs/api.md ~3077 lines hand-maintained drift risk

- [Low][60] frontend/src/api/client.ts:150 — EmailListResponse success?: boolean weak TS contract

- [Low][60] mail_core/accounts/credentials.py:32 — EnvCredentialStore.put_secret mutates process env only

- [Low][60] outlook_web/segments/08_forwarding_scheduler_errors.py:1 — print/safe_console_print as primary ops log in Flask scheduler

- [Low][60] tests/mail_core/ — scattered assert is not None weak assertions

- [Low][55] AGENTS.md:71 — AGENTS 770+ test count may be stale

- [Low][55] mail_core/mail/storage/models.py:1 — no explicit index on attachments(message_id)

- [Low][55] mail_core/providers/imap.py:68 — IMAP use_ssl defaults False

- [Low][55] tests/test_frontend_contract.py:4 — route-existence smoke thin; amplified as CI-only backend test

- [Low][55] web_outlook_app.py:47 — exec segment loader maintainability (see V5-A1)

- [Low][55] web_outlook_app.py:66 — DesktopServer ready.wait(15) generic timeout

- [Low][50] BRANCH_PROTECTION.md:1 — BRANCH_PROTECTION/RELEASE/CHANGELOG multi-entry (acceptable if linked)

- [Low][50] frontend/src/api/mailCore.mutations.test.ts:5 — vi.mock mailCoreFlag may mask flag parsing errors

- [Low][50] mail_core/api/app.py:19 — listener wait_started(5) then continues if not started

- [Low][50] mail_core/worker/main.py:56 — worker poll sleep fixed 2s even when queue deep

- [Low][50] web_outlook_app.py:23 — SEGMENT_FILES tuple must stay manually ordered

- [Low][45] tests/test_imap_folder_resolution.py:1 — 4k+ line test file mirrors god-file smell

- [Info][90] git history — contributor personal emails in public git authors/history

- [Info][90] mail_core/ — mail_core modular layout matches architecture intent (strength)

- [Info][90] mail_core/mail/application/queries.py:84 — keyset inbox pagination limit+1 is sound (strength)

- [Info][85] mail_core/sync/jobs.py:49 — SKIP LOCKED job claim + limit (strength)

- [Info][85] mail_core/sync/leases.py:1 — lease+fencing+delta rate-limit requeue pattern (strength)

- [Info][80] outlook_web/segments/01_bootstrap.py:1157 — Flask sanitize_error_details + trace_id (strength; reuse in mail_core)

- [Info][80] tests/conftest.py:10 — test DB isolation + frontend dist fixture strengths

- [Info][75] docs/known-limitations.md:1 — known-limitations + mail-core-status structure strengths (tone/content need updates)

- [Info][70] mail_core/api/mail.py:248 — path-shaped attachment route explicitly rejected (strength)

- [Info][50] mail_core/providers/oauth.py:86 — expires_at None forever-valid (see C3 High)

- [Info][40] frontend/src/api/client.ts:96 — treats res.redirected as 401 (false session clear)
