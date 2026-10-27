> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

# Cross-validation (Critical/High light falsification)

- **Target**: TuTouPower/kkmail (public)
- **SHA**: `b2956445574ebf171c1e73526421f0d46ccac3a3`
- **Method**: Open each Critical/High cited file:line in `/workspace/kkmail`; AGREE / CHALLENGED (with counter-evidence + lowered conf) / CONNECT (shared root cause). No application code edits. Zero-drop: CHALLENGED retained.
- **Date**: 2026-10-21 (Asia/Shanghai)

## Disposition summary

- **AGREE**: 37
- **CHALLENGED**: 3
- **CONNECT**: 1
- **SURFACE**: 0
- **Critical+High reviewed**: 41
- **SURFACE**: 0 (no new Critical/High discovered during falsification)

## CHALLENGED Criticals

None. All four Criticals (S1–S4) AGREE.

## CHALLENGED Highs

- **C2** conf 85→70: Code paths differ (verify_password vs verify_login_password) but init_db hashes LOGIN_PASSWORD into settings on first start (01_bootstrap ~1990-2006), so normal /login uses bcrypt and works. Divergence only if login_password setting missing/empty (plaintext env fallback). Lower conf; keep finding.
- **C4** conf 78→65: SSE keepalive does call dispatch_once (sse.py:~80); listener+worker also dispatch. However dispatch_once marks rows dispatched after fanout — duplicate side effects limited to race window, not unbounded worker mutation. Finding title overweighted cursor-gap; dual-tick still real. Lower conf.
- **V6-R5** conf 82→72: Helper truly lacks kwargs.setdefault("timeout",...). However audited call sites either pass timeout=HTTP_REQUEST_TIMEOUT or forward \*\*kwargs from wrappers whose callers pass timeout. Residual risk only on future omissions. Lower conf; keep.

## CONNECT pairs

- S2 ↔ S4 (default \*\*\* / weak SECRET_KEY)
- V4-H9 ↔ V6-R2 (reclaim_stale_claims unused — dedup machine line)
- C1 ↔ V6-R6 (outlook_mail_reader.py NameError + secret prints)
- C3 ↔ S25 Info (expires_at None)
- S8 ↔ V3 Medium Content-Disposition (keep High only in machine file)
- S21 / V3-M / V6-M `/ready` (dedup Medium)
- C7 ↔ V3-M optional POST body default True (dedup Medium)
- S11 ↔ C10 (datetime.max permanent cookie)

## Table

|FindingID|Sev|OrigConf|NewConf|Disposition|Counter-evidence or confirm note|file:line|
|---|---|---:|---:|---|---|---|
|S1|Critical|95|97|AGREE|Confirmed: FastAPI app has CORS only, no auth dependency on mail/sse routers; compose binds 0.0.0.0:8000. Architecture doc prefers loopback but compose contradicts. Raised conf.|mail_core/api/app.py:33-41|
|S2|Critical|92|92|AGREE|Confirmed docker.sock + LOGIN_PASSWORD=\*\*\* + SECRET_KEY=\*\*\* + DOCKER_UPDATE_ENABLED in default docker-compose.yml. Note: file comments redirect kkmail users to docker-compose.react.yml (which requires env secrets) — still ships insecure defaults as compose.yml. CONNECT S4.|docker-compose.yml:8-18|
|S3|Critical|90|92|AGREE|Confirmed deterministic hashlib fallback when keys unset; compose ships AAAA…/BBBB… sample keys. Raised conf.|mail_core/blobs/crypto.py:59-61|
|S4|Critical|88|90|AGREE|Confirmed .env.example + LOGIN_PASSWORD=os.getenv(...,"\*\*\*") at 01_bootstrap.py:164. CONNECT S2 (same default password in compose).|.env.example:7-11; outlook_web/segments/01_bootstrap.py:164|
|S5|High|90|88|AGREE|Confirmed GET /api/accounts/refresh-all @login_required. SameSite=Lax blocks cross-site <img> subresource CSRF but still sends cookie on top-level GET navigations — state-changing GET remains CSRF-able. Slight conf trim.|outlook_web/segments/05_routes_refresh_mail.py:1606-1610|
|S6|High|88|88|AGREE|Confirmed normalize_git_skin_url only checks empty/length/leading-/newlines then git clone; no scheme/host allowlist.|outlook_web/segments/01_bootstrap.py:3267-3304|
|S7|High|85|85|AGREE|Confirmed token_uri() returns credential JSON token_uri then urlopen; requires write to credential store (not anonymous HTTP). Still SSRF/exfil if credential_ref compromised.|mail_core/providers/oauth.py:75-146|
|S8|High|85|85|AGREE|Confirmed Content-Disposition embeds raw filename in quotes. Dedup drop V3 Medium same issue.|mail_core/api/mail.py:240-245|
|S9|High|82|88|AGREE|Confirmed api_get_settings returns plaintext external_api_key/duckmail/smtp/webdav/telegram/etc and never pops login_password (only adds masked). Raised conf.|outlook_web/segments/07_routes_oauth_settings_external.py:579-670|
|S10|High|80|82|AGREE|Confirmed api_key from query args; CORS * on /api/external/\*. Raised conf slightly.|outlook_web/segments/03_mail_helpers.py:3326-3345; 01_bootstrap.py:122-129|
|S11|High|78|78|AGREE|Confirmed SESSION_COOKIE_HTTPONLY+Lax only; no SECURE. Permanent sessions use datetime.max. CONNECT C10.|outlook_web/segments/01_bootstrap.py:79-81,3365-3371|
|S12|High|75|82|AGREE|Confirmed login uses X-Forwarded-For leftmost despite ProxyFix(x_for=1) already setting remote_addr — bypasses trusted hop. Raised conf.|outlook_web/segments/04_routes_groups_accounts.py:12-19|
|S13|High|78|80|AGREE|Confirmed ports 5433:5432 + POSTGRES_PASSWORD=\*\*\* in mail-core compose.|docker-compose.mail-core.yml:18-19|
|C1|High|92|95|AGREE|Confirmed outlook_mail_reader.py:41 uses os.getenv with no import os. CONNECT R6 (same file secret prints).|outlook_mail_reader.py:41|
|C2|High|85|70|CHALLENGED|Code paths differ (verify_password vs verify_login_password) but init_db hashes LOGIN_PASSWORD into settings on first start (01_bootstrap ~1990-2006), so normal /login uses bcrypt and works. Divergence only if login_password setting missing/empty (plaintext env fallback). Lower conf; keep finding.|outlook_web/segments/04_routes_groups_accounts.py:43-44|
|C3|High|80|82|AGREE|Confirmed \_access_valid returns True when expires_at is None. CONNECT S25 Info.|mail_core/providers/oauth.py:81-88|
|C4|High|78|65|CHALLENGED|SSE keepalive does call dispatch_once (sse.py:~80); listener+worker also dispatch. However dispatch_once marks rows dispatched after fanout — duplicate side effects limited to race window, not unbounded worker mutation. Finding title overweighted cursor-gap; dual-tick still real. Lower conf.|mail_core/api/sse.py:48-92|
|V3-H1|High|95|97|AGREE|Confirmed ViewState.accountId:number; MessageList String(view.accountId) into mail-core UUID query → 422. Raised conf.|frontend/src/store/mailStore.ts:8; MessageList.tsx:50-56; mail_core/api/mail.py:56|
|V3-H2|High|92|92|AGREE|Confirmed mailCoreToMailItem sets accountEmail: m.account_id (UUID) and accountId: undefined.|frontend/src/api/mailCore.ts:81-95|
|V3-H3|High|90|92|AGREE|Confirmed MessageOut/MailCoreMessage lack is_flagged; flag endpoint returns it. Raised conf.|mail_core/api/mail.py:33-44|
|V4-H4|High|93|95|AGREE|Confirmed \_recompute_folder_stats loads all Message rows via .all() then len/sum. Raised conf.|mail_core/sync/metadata.py:81-95|
|V4-H5|High|90|90|AGREE|Confirmed only UNIQUE(message_id,folder_id); no folder_id-leading index; PG does not auto-index FK.|mail_core/mail/storage/models.py:109-116|
|V4-H6|High|88|88|AGREE|Confirmed local_remote_ids_for_folder unbounded .all().|mail_core/sync/engine.py:246-252|
|V4-H7|High|85|85|AGREE|Confirmed IMAP4/IMAP4_SSL constructed with no timeout arg.|mail_core/providers/imap.py:70-73|
|V4-H8|High|82|85|AGREE|Confirmed mailCore getJson/postJson omit timeout; Flask client has MAIL_FETCH_TIMEOUT_MS=45s. Raised conf.|frontend/src/api/mailCore.ts:30-51|
|V4-H9|High|80|90|AGREE|Confirmed reclaim_stale_claims defined/exported but worker/main.py \_tick only claim_jobs+handle_job. CONNECT V6-R2 — DEDUP to single machine line at conf 90.|mail_core/sync/jobs.py:82-108; mail_core/worker/main.py:29-72|
|V5-A1|High|98|98|AGREE|Confirmed exec(compile(...), globals()) of 12 segments into flat namespace.|web_outlook_app.py:23-50|
|V5-A2|High|95|95|AGREE|Confirmed TOKEN_URL\_\* / token refresh reimplemented in segments, outlook_mail_reader.py, and mail_core/providers/oauth.py.|outlook_web/segments/01_bootstrap.py:168-170; outlook_mail_reader.py; mail_core/providers/oauth.py|
|V5-A3|High|92|90|AGREE|Confirmed mutations imports enqueue_job and private \_recompute_folder_stats. Domain AccountRef/MessageMetadata unused outside domain package (enums/archive are used — note). Slight conf trim.|mail_core/mail/application/mutations.py:14-15,77|
|V5-A4|High|90|90|AGREE|Confirmed api/mail.py imports blobs/search directly; sse.py imports OutboxEvent ORM.|mail_core/api/mail.py:12-28; mail_core/api/sse.py:15-18|
|V6-R1|High|93|95|AGREE|Confirmed fail_job sets FAILED only; attempts incremented on claim but never used for backoff requeue. Raised conf.|mail_core/sync/jobs.py:76-79|
|V6-R2|High|90|90|CONNECT|Same root cause as V4-H9: reclaim_stale_claims never called from worker. Dedup in machine file.|mail_core/sync/jobs.py:82-108; mail_core/worker/main.py:29-72|
|V6-R3|High|88|88|AGREE|Confirmed enqueue_job always INSERT; only claim index; no dedup unique.|mail_core/sync/jobs.py:16-35; models.py:278-298|
|V6-R4|High|85|88|AGREE|Confirmed idempotency_key UNIQUE; enqueue_remote_operation always INSERT without ON CONFLICT/lookup. Raised conf.|mail_core/mail/application/remote_ops.py:15-41; models.py:220|
|V6-R5|High|82|72|CHALLENGED|Helper truly lacks kwargs.setdefault("timeout",...). However audited call sites either pass timeout=HTTP_REQUEST_TIMEOUT or forward \*\*kwargs from wrappers whose callers pass timeout. Residual risk only on future omissions. Lower conf; keep.|outlook_web/segments/03_mail_helpers.py:295-308|
|V6-R6|High|80|85|AGREE|Confirmed prints Refresh Token[:30] and ret.text[:200]; CONNECT C1 NameError. Raised conf on leak evidence.|outlook_mail_reader.py:41,123-130,409|
|V7-H1|High|95|97|AGREE|Confirmed tests.yml runs only two pytest modules; paths omit mail_core/\*\*. Raised conf.|.github/workflows/tests.yml:20|
|V7-H2|High|92|95|AGREE|Confirmed frontend.yml only npm run build. Raised conf.|.github/workflows/frontend.yml:24-25|
|V7-H3|High|90|92|AGREE|Confirmed composeGraphMailBtn only in legacy templates/static; SPA Sidebar groups by group_id flat (no parent_id tree indent). Raised conf.|tests/test_outlook_graph_send_mail_frontend.py; frontend/src/components/Sidebar.tsx|
|V7-H4|High|88|95|AGREE|Confirmed AGENTS.md Trellis block; .trellis/ and .agents/ absent. Raised conf.|AGENTS.md:1-21|
|V8-H5|High|90|90|AGREE|Confirmed README ~811 lines duplicates deployment compose/\*\*\* examples also in docs/deployment.md. Labeled High in bundle (under Medium section heading — severity tag wins).|README.md; docs/deployment.md|
