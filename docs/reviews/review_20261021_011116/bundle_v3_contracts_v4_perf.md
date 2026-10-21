> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

# Intensive Review — Perspectives 3 (Contracts/Breaking/Types) + 4 (Performance/Resources)

- **Target**: TuTouPower/kkmail (mail_core API/DB/sync/search/worker + frontend api)
- **SHA**: `b2956445574ebf171c1e73526421f0d46ccac3a3`
- **Date**: 2026-10-21 (Asia/Shanghai)
- **Filter**: zero (all findings retained)
- **Scope files**: `mail_core/api/*`, `mail_core/db/*`, `mail_core/sync/*`, `mail_core/search/*`, `mail_core/worker/*`, `mail_core/mail/application/*`, `mail_core/mail/storage/models.py`, `mail_core/blobs/access.py|store.py`, `frontend/src/api/{client,queries,mailCore}.ts`, `frontend/src/components/MessageList.tsx`, `frontend/src/store/mailStore.ts`

## Summary

|Perspective|Focus|
|---|---|
|V3 Contracts|API shapes, status codes, validation, FE↔BE type IDs, schema/response_model gaps, dual Flask/mail-core bridge|
|V4 Perf|N+1, missing LIMIT/indexes, pool/timeouts, full-table loads, sync loops, FE fan-out|

- **Findings**: C/H/M/L/Info = **0 / 9 / 15 / 6 / 3** (total **33**)
- **Verdict (this bundle only)**: **REQUEST CHANGES** (no Critical in these two perspectives; multiple High)

______________________________________________________________________

## Critical / High (必修)

### [H][95] V3 — Flask `accountId: number` passed as mail-core `account_id: UUID`

- **Where**: `frontend/src/store/mailStore.ts:8`, `frontend/src/components/MessageList.tsx:50-56`, `mail_core/api/mail.py:56`, `frontend/src/api/mailCore.ts:74`
- **Evidence**: View type is `{ accountId: number }` (Flask integer PK). When mail-core list is preferred, MessageList does `accountId: String(view.accountId)` → query `account_id=1`. FastAPI declares `account_id: UUID | None`, so non-UUID values → **422**. Even if somehow accepted, mail-core `accounts.id` is UUID and will not match Flask ints.
- **Impact**: Single-account mail-core inbox path is contract-broken at the FE↔BE boundary.
- **Fix**: Maintain a Flask-id ↔ mail-core-UUID map (or stop passing Flask ids). Only send real UUIDs; validate with Zod/`uuid` before fetch. Until mapped, disable per-account mail-core query and use all-inbox / email lookup.

### [H][92] V3 — `mailCoreToMailItem` maps `accountEmail` to UUID, drops numeric `accountId`

- **Where**: `frontend/src/api/mailCore.ts:81-95`, consumers `queries.ts:192-198`, `MessageList` delete/mark-read grouping by `accountEmail`
- **Evidence**:
    ```ts
    accountEmail: m.account_id,  // UUID string, not email
    accountId: undefined,
    ```
    Flask path uses real email + numeric id. Mark-read/delete group by `accountEmail`; UI labels/show account email.
- **Impact**: Wrong labels; Flask fallback mutations keyed by email fail or mis-route for mail-core rows.
- **Fix**: Join account email from mail-core accounts API (or embed `email` in inbox DTO). Keep `account_id` UUID in a separate field (`mailCoreAccountId`).

### [H][90] V3 — Inbox list DTO omits `is_flagged` while flag mutation exists

- **Where**: `mail_core/api/mail.py:33-44` (`MessageOut`), `mail.py:206-222` (flag endpoint), `frontend/src/api/mailCore.ts:4-15`, `queries.ts:224-238`
- **Evidence**: DB has `Message.is_flagged`; POST `/flag` returns it; list/`MailCoreMessage` never expose it. FE flag UI relies on local `flaggedIds`, not server truth → refresh loses flag state for mail-core rows.
- **Fix**: Add `is_flagged: bool` to `MessageOut` / `MailCoreMessage` and map in `mailCoreToMailItem`.

### [H][93] V4 — `_recompute_folder_stats` loads entire folder into ORM (no aggregate, called per page/mutation)

- **Where**: `mail_core/sync/metadata.py:81-95`, callers `metadata.py:124`, `delta.py:94`, `mutations.py:77`, `reconcile.py:98-106`
- **Evidence**:
    ```python
    rows = session.scalars(select(Message).join(...).where(folder_id==...)).all()
    total = len(rows); unread = sum(1 for m in rows if not m.is_read)
    ```
    Runs after **every** metadata page (~20 pages × folders), every delta page, every mark-read.
- **Impact**: O(folder size) memory + CPU per sync page; large mailboxes thrash DB and worker.
- **Fix**: `SELECT count(*), count(*) FILTER (WHERE NOT is_read) FROM messages JOIN message_locations …`; or incremental ±1 on known transitions.

### [H][90] V4 — `message_locations` lacks `(folder_id)` / `(folder_id, message_id)` index for inbox path

- **Where**: `mail_core/mail/storage/models.py:109-116`, migration `20261020_0002…py:231-239`, query `queries.py:72-84`
- **Evidence**: Only `UNIQUE(message_id, folder_id)` (leading `message_id`). Hot path filters `MessageLocation.folder_id.in_(…)` then orders by `Message.sort_time`. Planner cannot efficiently seek by folder.
- **Impact**: Unified inbox / folder lists degrade to seq scans as mail grows.
- **Fix**: `CREATE INDEX ix_message_locations_folder ON message_locations (folder_id, message_id);` Consider covering join strategy / composite with messages.sort_time via redesign.

### [H][88] V4 — `local_remote_ids_for_folder` unbounded SELECT of all remote_ids

- **Where**: `mail_core/sync/engine.py:246-252`, used by `reconcile.py:48` then `provider.reconcile(remote_folder, local_ids)`
- **Evidence**: `.all()` with no LIMIT; entire folder ID set held in Python + sent to provider.
- **Impact**: Memory spike / huge payloads on large folders during reconcile.
- **Fix**: Stream in chunks; or push set-diff into SQL/`EXCEPT`; pass hashed/chunked ID sets to provider.

### [H][85] V4 — IMAP provider has no socket/connect timeout

- **Where**: `mail_core/providers/imap.py:70-73` (`IMAP4`/`IMAP4_SSL` with no timeout), contrast `oauth.py:146` (`timeout=30`)
- **Evidence**: Default imaplib can block indefinitely on hung servers; sync loop holds lease/worker slot.
- **Fix**: `imaplib.IMAP4_SSL(host, port, timeout=30)` (3.9+) or `sock.settimeout`; fail lease early.

### [H][82] V4 — mail-core frontend client has no request timeout (Flask path does)

- **Where**: `frontend/src/api/mailCore.ts:30-51` vs `queries.ts:115` / `client.ts:42-67` (`MAIL_FETCH_TIMEOUT_MS = 45_000`)
- **Evidence**: `getJson`/`postJson` only forward optional `signal`; callers often omit timeout. Hung mail-core stalls UI forever while Flask path aborts at 45s.
- **Fix**: Wrap with same `withTimeout` / default `timeoutMs: 45_000` in mailCore fetch helpers.

### [H][80] V4 — Worker never calls `reclaim_stale_claims` → CLAIMED jobs can stick forever

- **Where**: `mail_core/sync/jobs.py:82-108`, `mail_core/worker/main.py:29-72` (only `claim_jobs` + `handle_job`)
- **Evidence**: `reclaim_stale_claims` exported but unused by worker loop. Crash mid-job leaves `status=claimed` until manual intervention. Also reclaim itself has **no LIMIT** (loads all stale rows).
- **Impact**: Sync stalls; resource leak of job queue capacity.
- **Fix**: Periodic reclaim in `run()`; add `.limit(N)` to reclaim query; optionally expire claims with SQL `UPDATE … WHERE locked_at < now()-interval`.

______________________________________________________________________

## Medium

### [M][88] V3 — Search API returns only IDs; no hydrate / cursor / total contract

- **Where**: `mail_core/api/mail.py:109-119`, `search/index.py:40-76`
- **Evidence**: `{"query", "message_ids"}` only. Clients must N+1 `GET /messages/{id}` (or have no UI). No `response_model`, no pagination cursor beyond hard `limit`.
- **Fix**: Return `MessageOut[]` (or documented hydrate endpoint); add OpenAPI model; keyset cursor.

### [M][85] V3 — Most mail-core routes lack `response_model`; error bodies are bare strings

- **Where**: `mail.py:87-106,121-174,187-245` vs inbox which has `PageOut`
- **Evidence**: Folder stats / message detail / mutations return ad-hoc dicts. `HTTPException(404, "…")` → `{"detail": "…"}` while Flask uses `{success, error}`. FE `mailCore.ts` throws `mail-core ${status}: ${text}` with no structured code.
- **Fix**: Pydantic response models + unified error envelope `{code, message}`; align FE parser.

### [M][80] V3 — Optional POST body defaults mutation to `True` (mark read/flag)

- **Where**: `mail.py:187-209` (`body: ReadBody | None = None` → `want = True if body is None`)
- **Evidence**: Empty POST `/read` marks read; accidental clients without JSON flip state to True only.
- **Fix**: Require body; or default to toggle; reject missing body with 422.

### [M][78] V3 — `/ready` always `{status:ready}` without DB/listener check

- **Where**: `mail_core/api/app.py:49-51`
- **Evidence**: K8s-style readiness contract violated; traffic accepted while DB down.
- **Fix**: Probe `SELECT 1` + listener alive; return 503 when not ready.

### [M][75] V3 — Dual list schemas: Flask `EmailListItem` all-optional vs mail-core strict `MessageOut`

- **Where**: `frontend/src/api/client.ts:160-183`, `mailCore.ts:4-20`, `queries.ts:16-29`
- **Evidence**: Bridge maps fields differently (`from` vs `from_address`, `date` vs `sort_time`, `body_preview` vs `snippet`). Easy silent empty fields.
- **Fix**: Single normalized DTO at boundary; runtime schema check (zod).

### [M][72] V3 — Attachment `Content-Disposition` embeds raw filename (quoting/encoding)

- **Where**: `mail.py:240-245`
- **Evidence**: `filename="{payload.filename}"` — quotes/non-ASCII break clients; header injection if filename has `"`.
- **Fix**: RFC 5987 `filename*=UTF-8''…` + sanitize; strip CR/LF/quotes.

### [M][70] V3 — Cursor query params vs `next_cursor` key naming undocumented

- **Where**: `mail.py:54-55, PageOut.next_cursor` uses `sort_time`/`message_id`; request uses `cursor_sort_time`/`cursor_message_id`
- **Evidence**: Works if FE maps (mailCore does), but OpenAPI shows loose `dict | None` — breaking if keys rename.
- **Fix**: Typed `CursorOut` / `CursorIn` models; document mapping.

### [M][88] V4 — Search `subject ILIKE '%q%'` / `similarity` without subject trigram index

- **Where**: `search/index.py:58-71`, FTS migration `20261021_0003` indexes `document` + `from_text` only
- **Evidence**: `OR subject ILIKE '%'||:q||'%'` forces seq scan on large `message_search`; `similarity(from_text,:q)` may not use GIN efficiently for threshold filter.
- **Fix**: Add `gin_trgm_ops` on `subject`; prefer FTS-only path when `plainto_tsquery` matches; make ILIKE opt-in.

### [M][85] V4 — Sync folder discovery N+1 SELECT per remote folder

- **Where**: `mail_core/sync/engine.py:81-84`
- **Evidence**: Loop `select(Folder).where(account_id, remote_id)` once per remote folder.
- **Fix**: Prefetch `dict[(remote_id)] = Folder` for account; upsert in memory.

### [M][82] V4 — Engine default pool only (`pool_pre_ping`), no size/overflow/timeout tuned

- **Where**: `mail_core/db/session.py:26`
- **Evidence**: `create_engine(resolved, pool_pre_ping=True, future=True)` — defaults pool_size=5, max_overflow=10. Concurrent: API + SSE sessions + worker + listener compete; SSE holds sync Session briefly then long-lived async with dispatcher ticks.
- **Fix**: Explicit `pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle`; separate engines for API vs worker if needed.

### [M][80] V4 — Attachment download loads full blob into memory

- **Where**: `blobs/store.py:96-97` (`read_bytes`), `blobs/access.py:82`, `mail.py:245` `Response(content=payload.data)`
- **Evidence**: Entire attachment buffered. Large MIME parts risk OOM under concurrent downloads.
- **Fix**: StreamingResponse / file iterator; size cap; range requests.

### [M][78] V4 — `reclaim_stale_claims` has no LIMIT (when used)

- **Where**: `sync/jobs.py:94-101`
- **Fix**: `.limit(100)` + loop.

### [M][75] V4 — Frontend all-inbox fans out up to 8 parallel Flask fetches (45s each)

- **Where**: `queries.ts:94`, `MessageList.tsx:73-81`, `Sidebar.tsx:30-33`
- **Evidence**: Intentional cap, but Sidebar **and** MessageList can both fire `useQueries` for same keys (cache helps) still cold-start 8× backend load. Serial `fetchAccounts` up to 100×200 pages.
- **Fix**: Prefer mail-core unified inbox (already exists); backend aggregated unread; lower ACCOUNT_MAX_PAGES or use streaming.

### [M][72] V4 — SSE keepalive triggers `dispatch_once` every 15s per connection

- **Where**: `mail_core/api/sse.py:74-82`
- **Evidence**: Each open EventSource runs dispatcher on timeout → N clients ≈ N× DB drains.
- **Fix**: Shared background dispatcher only; keepalive should not do work.

### [M][70] V4 — Metadata apply does per-message search upsert + thread assign + outbox insert (write amplification)

- **Where**: `metadata.py:108-123`
- **Evidence**: For each meta: upsert message, upsert search, maybe thread, add OutboxEvent; then full stats recompute.
- **Fix**: Bulk insert outbox; defer search/thread to batch job; incremental stats.

______________________________________________________________________

## Low

### [L][75] V3 — Duplicate body endpoints (`GET /messages/{id}` and `/body`)

- **Where**: `mail.py:121-174`
- **Fix**: Document one as canonical; deprecate other or make `/body` strip metadata only (already thinner).

### [L][70] V3 — `PageOut.next_cursor: dict | None` untyped

- **Where**: `mail.py:46-48`
- **Fix**: `class Cursor(BaseModel): sort_time: datetime; message_id: UUID`

### [L][65] V3 — Health returns version but no schema/migration revision

- **Where**: `app.py:44-46`
- **Fix**: Include alembic head for ops contract.

### [L][60] V3 — `EmailListResponse` / Flask APIs use `success?: boolean` optional — weak TS contract

- **Where**: `client.ts:150-183`
- **Fix**: Discriminated unions; narrow after fetch.

### [L][55] V4 — No index on `attachments(message_id)` beyond FK (PG may auto-index FK depending on version — not declared)

- **Where**: models Attachment; `queries.py:176`
- **Fix**: Explicit `ix_attachments_message_id`.

### [L][50] V4 — Worker poll sleep fixed 2s even when queue deep

- **Where**: `worker/main.py:56-72`
- **Fix**: Adaptive backoff / immediate re-tick when `handled > 0`.

______________________________________________________________________

## Info

### [I][90] V4 — Keyset pagination on inbox is correctly `limit+1` (good)

- **Where**: `queries.py:84-106`
- **Note**: Strong pattern; keep. Missing folder_id index still hurts.

### [I][85] V4 — Job claim uses `FOR UPDATE SKIP LOCKED` + limit (good)

- **Where**: `jobs.py:49-55`

### [I][70] V3 — Path-shaped attachment route explicitly rejected (good contract for M5)

- **Where**: `mail.py:248-254`

______________________________________________________________________

## Spec / contract alignment notes

|Expected (architecture / FE bridge)|Observed|
|---|---|
|mail-core account UUID identity|FE still uses Flask int `accountId` for mail-core queries|
|List includes flag state for local-first UI|`is_flagged` only on mutation response|
|Search usable from SPA|IDs-only payload|
|Ready = dependencies up|Always ready|
|Sync stats cheap|Full folder materialization|

______________________________________________________________________

## Strengths

- Keyset inbox pagination (`limit+1` + sort_time/id) is sound.
- SKIP LOCKED job claim and fencing-gated sync writes are the right shape.
- Attachment UUID-only access + explicit path rejection matches stated M5 contract.
- Flask client timeout + CSRF retry are thoughtfully designed (mail-core client should copy timeout).
- FTS table with GIN on `document` is a good base (extend trigram to subject).

______________________________________________________________________

## Appendix — Traceability

|ID|Perspective|Severity|Conf|Primary locus|
|---|---|---|---|---|
|H1|V3|High|95|MessageList accountId UUID|
|H2|V3|High|92|mailCoreToMailItem accountEmail|
|H3|V3|High|90|MessageOut missing is_flagged|
|H4|V4|High|93|\_recompute_folder_stats|
|H5|V4|High|90|message_locations folder index|
|H6|V4|High|88|local_remote_ids unbounded|
|H7|V4|High|85|IMAP no timeout|
|H8|V4|High|82|mailCore fetch no timeout|
|H9|V4|High|80|reclaim_stale unused|
|M1–M15|V3/V4|Medium|70–88|see body|
|L1–L6|V3/V4|Low|50–75|see body|
|I1–I3|V3/V4|Info|70–90|positives|

Counts: **High=9, Medium=15, Low=6, Info=3, Critical=0 → total 33**.
