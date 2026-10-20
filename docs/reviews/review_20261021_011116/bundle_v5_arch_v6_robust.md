> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

# Intensive Review — Perspectives 5 (Architecture/Maintainability) + 6 (Robustness/Observability)

- **Target**: TuTouPower/kkmail
- **SHA**: `b2956445574ebf171c1e73526421f0d46ccac3a3`
- **Date**: 2026-10-21 (Asia/Shanghai)
- **Filter**: zero (all findings retained)
- **Scope**: `mail_core/**` layering (domain/application/storage/api/worker/sync), duplication `web_outlook_app.py` / `outlook_mail_reader.py` / `mail_core`, empty catches, retries/timeouts/idempotency, secret/PII logging, dead code, oversized files, coupling

## Summary

| Perspective | Focus |
|---|---|
| V5 Architecture | Layering, duplication, god-namespace segments, dead abstractions, size/coupling smells |
| V6 Robustness | Empty/silent catches, permanent fail without retry, missing job reclaim, idempotency holes, secret logging |

- **Findings**: C/H/M/L/Info = **0 / 10 / 14 / 6 / 3** (total **33**)
- **Verdict (this bundle only)**: **REQUEST CHANGES** (no Critical in these two perspectives; multiple High)

---

## Critical / High (必修)

### [H][98] V5 — Flask backend is a god-namespace via `exec` of 12 segments (~26.6k LOC shared globals)
- **Where**: `web_outlook_app.py:23-50`, `outlook_web/segments/*.py` (合計 ~26644 lines)
- **Evidence**: Entry compiles each `NN_*.py` and `exec(code, globals())` into one flat module namespace. Segments share mutable globals; `__file__` is the entrypoint, not the segment (documented in `AGENTS.md`). Individual files: `05_routes_refresh_mail.py` 4578, `02_groups_accounts.py` 3916, `01_bootstrap.py` 3528, `03_mail_helpers.py` 3379 LOC.
- **Impact**: Divergent/shotgun change risk; no package imports, circular refs invisible, IDE/refactor/typecheck weak; upstream-merge friction (AGENTS.md warns to minimize edits).
- **Fix**: Stop growing segments; new code in real packages (`outlook_web/mail/…`). Long-term: migrate mail paths to `mail_core` and shrink segments. Short-term: forbid new logic in files >800 LOC; extract helpers to importable modules.

### [H][95] V5 — Triple duplication of OAuth/IMAP/Graph token + mail I/O (legacy segments + test script + mail_core)
- **Where**:
  - `outlook_web/segments/01_bootstrap.py:168-170` (`TOKEN_URL_*`)
  - `outlook_web/segments/03_mail_helpers.py:528+` (`get_access_token_graph*`, `get_access_token_imap*`, IMAP readers)
  - `outlook_mail_reader.py:33-40,105-346` (parallel TOKEN_URL + three token getters)
  - `mail_core/providers/oauth.py:39-40,90-127` (`OAuthTokenClient`)
  - `mail_core/providers/{graph,gmail,imap}.py`
- **Evidence**: Same Microsoft token endpoints and refresh-token grant reimplemented three times. Flask and mail_core are intentionally dual-running (`docs/mail-core-cutover.md`) but **protocol logic is not shared**. `outlook_mail_reader.py` is an orphan CLI clone (no in-repo references outside itself).
- **Impact**: Bugfix must land in multiple places; cutover drift (timeouts, rotation, error mapping) is inevitable.
- **Fix**: Single provider library owned by `mail_core/providers`; Flask segments call it (thin adapter). Delete or quarantine `outlook_mail_reader.py` from the product tree (`scripts/dev/` or remove).

### [H][92] V5 — Application layer imports sync internals (and a private `_` helper)
- **Where**: `mail_core/mail/application/mutations.py:14-15,77`; architecture intent `docs/mail-core-architecture.md` § Dom vs Sync
- **Evidence**:
  ```python
  from mail_core.sync.jobs import enqueue_job
  from mail_core.sync.metadata import _recompute_folder_stats
  ...
  _recompute_folder_stats(session, folder.id)
  ```
  Domain package (`mail_core/mail/domain/models.py` `AccountRef`/`MessageMetadata`/…) is **exported but unused** outside `domain/` — UI/API talk to storage ORM + sync helpers instead.
- **Impact**: Layering collapse: “application” cannot evolve without sync; private `_recompute_folder_stats` becomes a cross-module API; domain models are dead weight (rejected inheritance / speculative generalization).
- **Fix**: Promote `recompute_folder_stats` to a public storage/application service; application should depend on ports (enqueue interface), not `sync.*`. Wire domain DTOs in queries or delete unused domain models.

### [H][90] V5 — API layer bypasses application for blobs/search; SSE reaches storage ORM directly
- **Where**: `mail_core/api/mail.py:12-28`, `mail_core/api/sse.py:15-18`
- **Evidence**: Router imports `blobs.access`, `blobs.store`, `search.index`, and `mail.storage.models.OutboxEvent` directly alongside `mail.application.*`. Architecture diagram expects API → Domain/Application → PG/Blob.
- **Impact**: Business rules for attachment ACL / search cannot be centralized; tests must hit FastAPI or duplicate logic.
- **Fix**: Thin application facades (`get_attachment_bytes`, `search_mailbox`, `read_outbox_since`) and keep routers transport-only.

### [H][93] V6 — Worker permanently `FAILED` with no backoff requeue; `attempts` incremented but unused
- **Where**: `mail_core/sync/jobs.py:66,76-79`; `mail_core/worker/handlers.py:134-137`; `mail_core/worker/main.py:47-51`
- **Evidence**: `fail_job` sets `status=FAILED` only. Claim bumps `attempts` but nothing schedules `PENDING` + `run_after` with exponential backoff. Transient network/`RateLimitedError` outside delta’s local handler → permanent failure.
- **Impact**: One blip loses sync/archive/push until manual DB surgery.
- **Fix**: `fail_job` → if `attempts < N`: set PENDING, `run_after=now+backoff(attempts)`, else DEAD/FAILED. Alert on dead-letter.

### [H][90] V6 — `reclaim_stale_claims` never called from worker loop (CLAIMED jobs can stick forever)
- **Where**: `mail_core/sync/jobs.py:82-108`; `mail_core/worker/main.py:29-72`
- **Evidence**: Function exported from `mail_core.sync` but worker `_tick` only `claim_jobs` + `handle_job`. Crash after claim commit leaves rows `claimed` indefinitely. (May overlap V4 perf bundle; retained for robustness.)
- **Impact**: Account sync stalls under worker death/OOM.
- **Fix**: Call `reclaim_stale_claims` each poll (or timer); add LIMIT; metrics on reclaim count.

### [H][88] V6 — `worker_jobs` has no idempotency/dedup key → duplicate sync storms
- **Where**: `mail_core/mail/storage/models.py:278-298`; `mail_core/sync/jobs.py:16-35`; enqueue sites `mail_core/sync/engine.py:101-107`, `mutations.py:36-42`, `delta.py:196-203`
- **Evidence**: Only claim index on `(status, run_after, priority)`. `enqueue_job` always INSERTs. Folder discovery enqueues `SYNC_FOLDER_METADATA` per folder every run; `_wake_push` enqueues another `REMOTE_OPERATION_PUSH` per mutation; rate-limit path enqueues another delta while old job completes.
- **Impact**: Worker backlog explosion; duplicate provider load; lease contention.
- **Fix**: Unique partial index on `(job_type, account_id, payload_hash) WHERE status IN ('pending','claimed')` or upsert-by-natural-key before insert.

### [H][85] V6 — Remote-op `idempotency_key` unique but enqueue does not upsert → IntegrityError on re-toggle
- **Where**: `mail_core/mail/application/remote_ops.py:15-41`; `mutations.py:67,117`; `models.py:220`
- **Evidence**: Key is `f"{msg.id}:read:{int(is_read)}"`. Second identical mark-read (or retry after partial commit) hits `UNIQUE(idempotency_key)` with no `ON CONFLICT` / select-existing path → 500 to API.
- **Impact**: Client retries / double-clicks break mutations; contradicts “desired-state” design.
- **Fix**: Look up by idempotency_key; if pending, refresh `desired_state`; if terminal, insert new key with timestamp or reuse entity_key coalescing (§9 desired-state).

### [H][82] V6 — `request_with_proxy_failover` does not enforce a default timeout
- **Where**: `outlook_web/segments/03_mail_helpers.py:295-308`
- **Evidence**: Forwards `**kwargs` to `requests.request` with no `kwargs.setdefault("timeout", HTTP_REQUEST_TIMEOUT)`. Callers usually pass timeout, but any omission → indefinite hang on outbound Graph/token calls (holds Flask threaded worker).
- **Fix**:
  ```python
  kwargs.setdefault("timeout", HTTP_REQUEST_TIMEOUT)
  ```

### [H][80] V6 — Orphan `outlook_mail_reader.py` prints refresh-token prefix + raw token error bodies; missing `os` import
- **Where**: `outlook_mail_reader.py:41` (`os.getenv` without `import os`), `:123-130`, `:409`
- **Evidence**:
  ```python
  print(f"Refresh Token: {REFRESH_TOKEN[:30]}..." if REFRESH_TOKEN else "未设置")
  print(f"     响应: {ret.text[:200]}...")
  ```
  Script invites hardcoding secrets at top; on failure dumps up to 200 chars of token endpoint body (may include error payloads). `IMAP_TIMEOUT = int(os.getenv(...))` → `NameError` if imported/run as module before main config.
- **Impact**: Accidental credential leakage in shell history/CI logs; dead/dangerous footgun in repo root.
- **Fix**: Remove from root or move under `scripts/` with env-only secrets, never print token material; add `import os` or delete.

---

## Medium / Low / Info (建议)

### [M][88] V5 — Dual product stacks (Flask SQLite mail cache + mail_core PG) without shared domain boundary
- **Where**: `docs/mail-core-cutover.md`, `mail_core/README.md:5`, `frontend` feature flags `VITE_MAIL_CORE*`
- **Evidence**: Cutover keeps Flask login/send + list fallback while mail-core owns list/reader when flagged. Two schemas, two ID spaces (int vs UUID — see V3), duplicated provider code.
- **Impact**: Shotgun features; “which truth?” bugs during cutover.
- **Fix**: Time-box cutover; forbid new Flask mail-list features; adapter only.

### [M][85] V5 — Dual UIs (`static/js/index/*` + `frontend/`) both live
- **Where**: `static/js/index/` (~15 segment JS files, `01-core.js` 2980 LOC), `frontend/src/`, served via `12_routes_react_spa.py` `/` vs `/legacy`
- **Evidence**: Legacy JS still maintained alongside React SPA.
- **Impact**: Divergent UX/security fixes (CSRF, sanitization) must land twice.
- **Fix**: Freeze legacy except security; document deprecation date.

### [M][80] V5 — Oversized “god files” beyond maintainability heuristic
- **Where**: `outlook_web/segments/05_routes_refresh_mail.py` (4578), `02_groups_accounts.py` (3916), `03_mail_helpers.py` (3379), `tests/test_imap_folder_resolution.py` (4581), `static/js/index/01-core.js` (2980)
- **Evidence**: Multiple files ≫ 800–1000 LOC heuristic; mixed routes + protocol + DB + scheduling in one file.
- **Fix**: Split by bounded context (refresh, delete, graph batch, imap).

### [M][78] V5 — Desktop entry duplicates shutdown/error swallowing
- **Where**: `web_outlook_app.py:84-91` (`except Exception: pass` on `http_server.shutdown`)
- **Evidence**: Silent ignore of shutdown failures; hard to diagnose hung desktop sidecar.
- **Fix**: Log at warning with `exc_info`.

### [M][75] V6 — ~47 `except Exception: pass` (+ ~135 bare `except Exception` blocks) in segments/mail_core
- **Where**: Heavy in `03_mail_helpers.py`, `02_groups_accounts.py`, `05_routes_refresh_mail.py`, `01_bootstrap.py`; mail_core mostly connection-close paths
- **Evidence**: Pattern count via search; example decrypt swallow in `02_groups_accounts.py:1014-1027` leaves ciphertext in `password`/`refresh_token` fields and continues.
- **Impact**: Auth failures look like “bad password”; operational issues hidden.
- **Fix**: Never pass on decrypt; mark account `needs_reauth`. Log+metric other passes; prefer narrow except.

### [M][78] V6 — `/ready` does not probe DB / listener; equals `/health`
- **Where**: `mail_core/api/app.py:44-51`
- **Evidence**: `ready()` returns static `{"status":"ready"}` with no session/`SELECT 1` or listener liveness.
- **Impact**: Orchestrators route traffic to a brain-dead API.
- **Fix**: Ping DB; optionally require outbox listener `is_alive`.

### [M][72] V6 — `fail_job(..., str(exc))` / `last_error` may store provider HTTP bodies
- **Where**: `handlers.py:137`, `main.py:51`; `ProviderHttpError` carries `body` (`providers/http.py`, `oauth.py:148-150`)
- **Evidence**: OAuth/HTTP errors include response text; persisted on `worker_jobs.last_error` and logged via `log.exception`.
- **Impact**: Token endpoint error descriptions / accidental token fragments in DB+logs.
- **Fix**: Persist `type(exc).__name__` + sanitized short message (reuse Flask `sanitize_error_details` patterns in mail_core).

### [M][70] V6 — Flask has `sanitize_error_details`; mail_core logging has no equivalent redaction helper
- **Where**: `outlook_web/segments/01_bootstrap.py:1161-1176` vs `mail_core/**` (`logging.getLogger` without redact)
- **Evidence**: Legacy consciously strips bearer/refresh/password; mail_core oauth comment says “Access tokens are never logged” but worker/exception paths have no shared sanitizer.
- **Fix**: Shared `mail_core.security.redact(text)` applied to all error strings leaving the process.

### [M][68] V6 — `resolve_account_record` silent decrypt failure
- **Where**: `outlook_web/segments/02_groups_accounts.py:1013-1027`
- **Evidence**: `except Exception: pass` after `decrypt_data` for password/refresh_token/imap_password.
- **Impact**: Downstream uses undecryptable blobs as tokens; confusing errors; possible log of ciphertext as if secret.
- **Fix**: Fail closed; set status flag; do not return undecrypted secrets to callers.

### [M][65] V6 — Rate-limit path in delta correctly re-enqueues, but handler still `complete_job` (OK) while folder discovery has no RateLimited handling
- **Where**: `sync/delta.py:193-206` (good); `sync/engine.py:61-62` `provider.list_folders()` uncaught RateLimited/network
- **Evidence**: `list_folders` network outside try; bubbles to `fail_job` permanent.
- **Fix**: Catch `RateLimitedError` in engine like delta; schedule delayed job.

### [M][70] V5 — `run_windows_desktop` is thin alias of `run_desktop_app` (dead indirection)
- **Where**: `web_outlook_app.py:130-131`
- **Evidence**: Pure forwarder; shotgun rename risk.
- **Fix**: Delete alias or document compatibility need.

### [M][60] V5 — mail_core domain archive FSM exists but application mutations ignore archive states
- **Where**: `mail_core/mail/domain/archive.py`; mutations only read/flag
- **Evidence**: Spec has archive state machine; API surface incomplete relative to domain package.
- **Impact**: Half-built abstraction invites inconsistent calls later.
- **Fix**: Either wire archive transitions through domain helpers or mark domain archive as future-only in docs.

### [M][55] V6 — Outbox LISTEN reconnect logs full exception; NOTIFY payload logged at debug
- **Where**: `mail_core/realtime/listener.py:88,102-106`
- **Evidence**: `log.debug("NOTIFY %s payload=%r", …)`; exception path `log.exception`. Payloads may include message subjects/ids (PII).
- **Fix**: Log event id/type only at info; redact payload.

### [M][50] V5 — Feature-flag cutover increases coupling between Flask inject config and Vite build flags
- **Where**: `docs/mail-core-cutover.md` (`MAIL_CORE_DEFAULT`, `VITE_MAIL_CORE*`)
- **Evidence**: Four overlapping switches; FE fallback paths multiply.
- **Fix**: Collapse to one runtime flag post-MVP.

### [L][70] V5 — Empty `__init__.py` packages with all logic in deep modules (OK) but public exports incomplete
- **Where**: `mail_core/mail/application/__init__.py` (0 bytes), `mail_core/api/__init__.py`
- **Fix**: Export stable façade or document “import submodule”.

### [L][65] V5 — Naming: `outlook_*` everywhere while product is kkmail / multi-provider
- **Where**: `web_outlook_app.py`, `outlook_web/`, `outlook_mail_reader.py`
- **Impact**: Onboarding confusion (Gmail/IMAP also supported in mail_core).
- **Fix**: Rename gradually post-cutover; keep upstream-compatible paths per AGENTS.md.

### [L][60] V6 — `print` / `safe_console_print` used as primary ops log in Flask scheduler
- **Where**: `08_forwarding_scheduler_errors.py` many lines; `05_routes_refresh_mail.py:635`
- **Evidence**: Mix of print and `app.logger`; no structured fields/trace correlation on some paths.
- **Fix**: Route through logger with `trace_id`.

### [L][55] V6 — DesktopServer `ready.wait(timeout=15)` then raises generic timeout
- **Where**: `web_outlook_app.py:66-70`
- **Fix**: Include underlying `self.error` if any; distinguish hang vs fail.

### [L][50] V5 — `SEGMENT_FILES` tuple must stay manually ordered
- **Where**: `web_outlook_app.py:23-36`
- **Impact**: Wrong order → subtle NameError at runtime.
- **Fix**: Import graph or package init instead of exec order.

### [L][45] V5 — Tests at 4k+ lines (`test_imap_folder_resolution.py`) mirror god-file smell
- **Where**: `tests/test_imap_folder_resolution.py` (4581)
- **Fix**: Split by scenario packs.

### [I][90] V5 — Strength: mail_core modular layout (api / worker / sync / providers / blobs) matches architecture doc intent
- **Where**: `mail_core/` tree, `docs/mail-core-architecture.md`
- **Note**: Directionally correct; issues are incomplete enforcement and dual-stack drag.

### [I][85] V6 — Strength: lease + fencing + SKIP LOCKED claim design; delta rate-limit requeue pattern
- **Where**: `sync/leases.py`, `sync/jobs.py:claim_jobs`, `sync/delta.py:193-206`
- **Note**: Keep; extend to all engine entrypoints and reclaim loop.

### [I][80] V6 — Strength: Flask `sanitize_error_details` + `build_error_payload` with `trace_id`
- **Where**: `01_bootstrap.py:1157-1204`
- **Note**: Reuse in mail_core rather than reinvent.

---

## Spec Compliance (mail-core architecture)

| Spec expectation | Status |
|---|---|
| API → Domain/Application → storage | **Partial** — API/blobs/search shortcut; application → sync private |
| Sync subsystem isolated | **Partial** — good package, but jobs lack dedup/retry/reclaim wiring |
| Provider isolation | **Partial** — mail_core OK; Flask segments still own parallel providers |
| Independent worker + SKIP LOCKED | **Present**; reclaim unused; fail permanent |
| SSE + outbox | **Present**; ready check weak |
| No Redis/Kafka | **Compliant** |

---

## Strengths

- Clear greenfield `mail_core` package boundaries and architecture doc.
- Fencing/lease + transactional outbox are the right robustness backbone.
- Legacy Flask error sanitization is thoughtful; should become shared.
- Cutover doc honestly states dual-run (reduces false “fully migrated” claims).

---

## Appendix — Traceability

| ID | Perspective | Severity | Conf | Primary locus |
|---|---|---|---|---|
| A1 | V5 | H | 98 | `web_outlook_app.py` exec segments |
| A2 | V5 | H | 95 | OAuth/IMAP triple clone |
| A3 | V5 | H | 92 | `application/mutations.py` → `sync._recompute_*` |
| A4 | V5 | H | 90 | `api/mail.py` / `sse.py` layering |
| R1 | V6 | H | 93 | permanent `fail_job` |
| R2 | V6 | H | 90 | unreclaimed CLAIMED jobs |
| R3 | V6 | H | 88 | no worker_jobs dedup |
| R4 | V6 | H | 85 | remote_ops idempotency IntegrityError |
| R5 | V6 | H | 82 | proxy failover timeout default |
| R6 | V6 | H | 80 | `outlook_mail_reader.py` secret prints |
| +14M / +6L / +3I | mixed | | | see body |

Rules/heuristics: intensive-review §视角5 (规模/重复/死代码/边界), §视角6 (空 catch/重试幂等/日志脱敏).
