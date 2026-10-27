# 审阅结果决策

- 来源报告：同目录 `review_intensive.md`（汇总 15 份 bundle，明细见下「报告来源」节）
- 审阅基线：`29dcd3a4a080a23423a32b02cce37ee546d48c97`（短写 `29dcd3a`，与同目录 `review_summary.md`、`review_intensive.md` 标题头一致）
- 决策日期：2026-10-25
- 条目区间与计数：采纳 A1–A296 共 296 项；不采纳 R1–R92 共 92 项；待决定 0 项（明细见下「统计」节）

## 目录

- [报告来源](#报告来源)
- [统计](#统计)
- [采纳项](#采纳项)（A1–A296）
- [不采纳项](#不采纳项)（R1–R92）

## 报告来源

- 已读：review_intensive.md；bundle_cross_validation.md；bundle_desktop_scripts.md；bundle_docs_archive.md；bundle_docs_live.md；bundle_docs_reviews.md；bundle_frontend_state.md；bundle_frontend_ui.md；bundle_mc_api_app.md；bundle_mc_data_crypto.md；bundle_mc_providers_sync.md；bundle_privacy_history.md；bundle_regression.md；bundle_regression_addendum.md；bundle_repo_tooling.md；bundle_root_ci.md。
- 缺失：无（该目录声明的 15 份 bundle 与 review_intensive.md 均存在；review_summary.md 不在读取白名单内）。
- 合并说明：review_intensive.md 汇总 454 项，其中 451 个带位置 finding 与 3 个跨域 surface；451 个位置均能在 bundle 找到。标准格式 finding 共 460 次出现，按位置归并为 451 项；同位置多报告映射见下方。bundle_cross_validation 的 67 个 Critical/High 复核结果已纳入；remote_ops:35 的 CHALLENGED 归 R，/health token 的 OVERSTATED 归 R。 PGPASSWORD literal finding经对照审阅基线代码证伪：`${PGPASSWORD:-}` 是环境变量展开，不是固定凭据；相关两项已转为 R。
- 回归补充：bundle_regression 的 9 个 CHANGED/STILL PRESENT 残余中，5 个并入同根因项（fetch-pg checksum、bootstrap password hash、tar link extraction、MessageList 行与复选框语义、tsconfig.node strictness）；4 个独立残余另行处置。bundle_regression_addendum 的重复项按相同位置归并。
- 密集归并：A294 合并 30 个历史凭据/个人数据/机器路径 finding 与 SURFACE-1；A293 合并 sync-body 的请求时序和失败反馈两项。Surface-2 归 R，因本轮聚合已去重且旧统计属历史；Surface-3 归 R，五个具体失败路径已分别处置，全仓 lint/规范建议范围过宽。
- 重复映射（报告行 → 决策编号）：
    - A1 ← bundle_cross_validation.md:L53, bundle_mc_data_crypto.md:L5
    - A2 ← bundle_cross_validation.md:L54, bundle_mc_data_crypto.md:L6
    - A3 ← bundle_cross_validation.md:L23, bundle_desktop_scripts.md:L4
    - A4 ← bundle_cross_validation.md:L25, bundle_desktop_scripts.md:L6
    - A5 ← bundle_cross_validation.md:L29, bundle_docs_live.md:L5
    - A6 ← bundle_cross_validation.md:L30, bundle_docs_live.md:L6
    - A7 ← bundle_cross_validation.md:L48, bundle_mc_api_app.md:L6
    - A8 ← bundle_cross_validation.md:L88, bundle_root_ci.md:L5
    - A9 ← bundle_cross_validation.md:L31, bundle_docs_live.md:L7
    - A10 ← bundle_cross_validation.md:L59, bundle_mc_providers_sync.md:L5
    - A11 ← bundle_cross_validation.md:L76, bundle_regression.md:L30, bundle_regression_addendum.md:L13
    - A12 ← bundle_cross_validation.md:L87, bundle_root_ci.md:L4
    - A13 ← bundle_cross_validation.md:L60, bundle_mc_providers_sync.md:L6
    - A14 ← bundle_cross_validation.md:L22, bundle_desktop_scripts.md:L3, bundle_regression.md:L52（不同位置，同根因：same-origin checksum trust root）
    - R85 ← bundle_cross_validation.md:L28, bundle_docs_archive.md:L8
    - A15 ← bundle_cross_validation.md:L45, bundle_frontend_state.md:L12, bundle_regression.md:L75
    - A16 ← bundle_cross_validation.md:L50, bundle_mc_api_app.md:L8
    - A17 ← bundle_cross_validation.md:L61, bundle_mc_providers_sync.md:L7
    - R83 ← bundle_cross_validation.md:L64, bundle_privacy_history.md:L7
    - R84 ← bundle_cross_validation.md:L65, bundle_privacy_history.md:L8
    - A18 ← bundle_cross_validation.md:L86, bundle_root_ci.md:L3
    - A19 ← bundle_cross_validation.md:L24, bundle_desktop_scripts.md:L5
    - A20 ← bundle_cross_validation.md:L51, bundle_mc_api_app.md:L9
    - A21 ← bundle_cross_validation.md:L63, bundle_mc_providers_sync.md:L9
    - A22 ← bundle_cross_validation.md:L55, bundle_mc_data_crypto.md:L7
    - A23 ← bundle_cross_validation.md:L57, bundle_mc_data_crypto.md:L9
    - A24 ← bundle_cross_validation.md:L62, bundle_mc_providers_sync.md:L8
    - A25 ← bundle_cross_validation.md:L56, bundle_mc_data_crypto.md:L8
    - A26 ← bundle_cross_validation.md:L58, bundle_mc_data_crypto.md:L10
    - A33 ← bundle_regression.md:L78（不同位置，同根因：non-strict Node TypeScript config）
    - A53 ← bundle_regression.md:L64（不同位置，同根因：unsafe archive link-member extraction）
    - A80 ← bundle_regression.md:L31（不同位置，同根因：nested row/checkbox interaction semantics）
    - A123 ← bundle_regression.md:L61（不同位置，同根因：initial password hash creation race）
    - A137 ← bundle_mc_providers_sync.md:L11, bundle_regression.md:L49
    - A155 ← bundle_privacy_history.md:L16, bundle_root_ci.md:L8
    - A156 ← bundle_privacy_history.md:L17, bundle_root_ci.md:L9
    - A177 ← bundle_regression.md:L59, bundle_root_ci.md:L27
    - A211 ← bundle_frontend_ui.md:L32, bundle_regression.md:L72
    - A246 ← bundle_mc_api_app.md:L67, bundle_regression.md:L44
    - A294 ← bundle_cross_validation.md:L32, bundle_cross_validation.md:L68, bundle_docs_reviews.md:L3, bundle_regression.md:L8, bundle_regression_addendum.md:L5, bundle_cross_validation.md:L33, bundle_docs_reviews.md:L4, bundle_cross_validation.md:L34, bundle_docs_reviews.md:L5, bundle_cross_validation.md:L35, bundle_docs_reviews.md:L6, bundle_cross_validation.md:L26, bundle_cross_validation.md:L67, bundle_docs_archive.md:L6, bundle_privacy_history.md:L10, bundle_cross_validation.md:L36, bundle_docs_reviews.md:L7, bundle_cross_validation.md:L37, bundle_docs_reviews.md:L8, bundle_cross_validation.md:L38, bundle_docs_reviews.md:L9, bundle_cross_validation.md:L40, bundle_cross_validation.md:L69, bundle_docs_reviews.md:L11, bundle_regression.md:L11, bundle_regression_addendum.md:L6, bundle_cross_validation.md:L27, bundle_docs_archive.md:L7, bundle_privacy_history.md:L12, bundle_cross_validation.md:L39, bundle_docs_reviews.md:L10, bundle_cross_validation.md:L66, bundle_privacy_history.md:L9, bundle_cross_validation.md:L44, bundle_docs_reviews.md:L15, bundle_docs_archive.md:L16, bundle_privacy_history.md:L11
    - A292 ← bundle_cross_validation.md:L46, bundle_frontend_ui.md:L5
    - A293 ← bundle_cross_validation.md:L49, bundle_mc_api_app.md:L7
    - R1 ← bundle_cross_validation.md:L71, bundle_docs_reviews.md:L20, bundle_regression.md:L19, bundle_regression_addendum.md:L8
    - R2 ← bundle_cross_validation.md:L70, bundle_regression.md:L18, bundle_regression_addendum.md:L7
    - R3 ← bundle_cross_validation.md:L72, bundle_regression.md:L21, bundle_regression_addendum.md:L9
    - R4 ← bundle_cross_validation.md:L73, bundle_docs_reviews.md:L23, bundle_regression.md:L23, bundle_regression_addendum.md:L10
    - R5 ← bundle_cross_validation.md:L74, bundle_regression.md:L25, bundle_regression_addendum.md:L11
    - R6 ← bundle_cross_validation.md:L41, bundle_docs_reviews.md:L12
    - R7 ← bundle_cross_validation.md:L47, bundle_mc_api_app.md:L5
    - R8 ← bundle_cross_validation.md:L75, bundle_regression.md:L33, bundle_regression_addendum.md:L12
    - R9 ← bundle_cross_validation.md:L42, bundle_docs_reviews.md:L13
    - R10 ← bundle_cross_validation.md:L43, bundle_docs_reviews.md:L14
    - R11 ← bundle_cross_validation.md:L52, bundle_mc_api_app.md:L10
    - R13 ← bundle_docs_reviews.md:L22, bundle_regression.md:L20
- 仅聚合项：review_intensive.md:L44 → A294；review_intensive.md:L145 → R81；review_intensive.md:L175 → R82。

## 统计

- 采纳：296 项（A1–A296）
- 不采纳：92 项（R1–R92）
- 待决定：0 项

## 采纳项

### A1. Sealed restore always fails on manifest filename case （预存， blame cae1fa6 2026-10-22)

- 来源：bundle_cross_validation, bundle_mc_data_crypto
- 位置：src/mail_core/backup/package.py:754
- 优先级：CRITICAL
- 详细判断理由：审阅在此处复核到“Sealed restore always fails on manifest filename case （预存， blame cae1fa6 2026-10-22)”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：read `extract_dir / "MANIFEST.json"` (and keep the name a single shared constant used by create/verify/restore)

### A2. Plain (unencrypted) backup packages can never be restored （预存）

- 来源：bundle_cross_validation, bundle_mc_data_crypto
- 位置：src/mail_core/backup/package.py:744
- 优先级：CRITICAL
- 详细判断理由：审阅在此处复核到“Plain (unencrypted) backup packages can never be restored （预存）”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：in the plain branch, treat the package directory itself as the extracted tree (or pack a tar at create time) instead of searching for a nonexistent `*.tar.gz`

### A3. Packaging soft-exit still masks electron-builder failure with exit 0 （预存， round-1 High still present in round 2)

- 来源：bundle_cross_validation, bundle_desktop_scripts
- 位置：src/desktop/scripts/pack-linux.js:131
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“Packaging soft-exit still masks electron-builder failure with exit 0 （预存， round-1 High still present in round 2)”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：exit non-zero on any builder failure/missing builder by default; make soft-ok an explicit opt-in (e.g. KKMAIL_PACK_SOFT=1) used only in local scaffolding, never in the npm pack scripts

### A4. Packaged smoke never actually verifies data persistence (AC-003 is illusory)

- 来源：bundle_cross_validation, bundle_desktop_scripts
- 位置：src/desktop/scripts/packaged-smoke.js:117
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“Packaged smoke never actually verifies data persistence (AC-003 is illusory)”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：write/read the marker through a retained client (or the manager's createdb/psql equivalent) with the real user/db, assert the read-back value after mgr2.start(), and fail if the client binary is absent

### A5. （预存） `list --unread` / `--flagged` silently return unfiltered inbox

- 来源：bundle_cross_validation, bundle_docs_live
- 位置：docs/skills/kkmail/scripts/kkmail_cli.py:394
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“（预存） `list --unread` / `--flagged` silently return unfiltered inbox”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：send `is_read=false` for `--unread` and `is_flagged=true` for `--flagged` in `list_inbox`, and add a CLI test asserting the emitted query string.

### A6. （预存） Handoff records a head_commit that does not exist in the repo

- 来源：bundle_cross_validation, bundle_docs_live
- 位置：docs/handoff.md:9
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“（预存） Handoff records a head_commit that does not exist in the repo”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：rewrite the section with the real current head (29dcd3a) and current focus, or run repo-hygiene to archive it and write a fresh section.

### A7. Missing `datetime` import silently breaks `_followup_run_after` scheduling

- 来源：bundle_cross_validation, bundle_mc_api_app
- 位置：src/mail_core/worker/handlers.py:66
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“Missing `datetime` import silently breaks `_followup_run_after` scheduling”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：add `from datetime import datetime` at module top and log (not silently pass) an unparseable `_followup_run_after`

### A8. （预存）CI OpenAPI gate never checks the live FastAPI schema

- 来源：bundle_cross_validation, bundle_root_ci
- 位置：.github/workflows/ci.yml:70
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“（预存）CI OpenAPI gate never checks the live FastAPI schema”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：add a backend CI step running `python scripts/export_openapi.py --check` with requirements-dev installed.

### A9. （预存） Security guide falsely states Electron permission handlers deny everything

- 来源：bundle_cross_validation, bundle_docs_live
- 位置：docs/guides/security.md:57
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“（预存） Security guide falsely states Electron permission handlers deny everything”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：state that all permissions are denied except `clipboard-sanitized-write` for the trusted top-level app frame, matching hardening.js and conventions.md §八.1.

### A10. Plaintext IMAP allowed by config with no STARTTLS, warning, or loopback restriction （预存）

- 来源：bundle_cross_validation, bundle_mc_providers_sync
- 位置：src/mail_core/providers/factory.py:133
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“Plaintext IMAP allowed by config with no STARTTLS, warning, or loopback restriction （预存）”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：refuse use_ssl=false for non-loopback hosts, or upgrade via STARTTLS before login, and log a loud warning when plaintext is configured

### A11. Live security guide still describes pre-DB password storage

- 来源：bundle_cross_validation, bundle_regression, bundle_regression_addendum
- 位置：docs/guides/security.md:5
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“Live security guide still describes pre-DB password storage”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：rewrite the bullet to name auth_credentials as authoritative and env/file as first-boot bootstrap only

### A12. （预存）Bare `docker compose up` yields an unmigrated, worker-less stack

- 来源：bundle_cross_validation, bundle_root_ci
- 位置：docker-compose.mail-core.yml:71
- 优先级：HIGH
- 详细判断理由：compose 示例与分布式 profile 的现有部署契约冲突；deployment guide 已要求明确启动 api/worker。仅需修正文档入口，不改动 profiles 或将 worker 混入 api。
- 修复说明：把 compose 顶部示例改为文档已支持的 `docker compose -f docker-compose.mail-core.yml up --build -d api worker`（或显式说明 distributed profile）；保留 migrate/worker profiles 与拆分架构。

### A13. Flag FETCH failure silently drops flag deltas while MODSEQ checkpoint advances

- 来源：bundle_cross_validation, bundle_mc_providers_sync
- 位置：src/mail_core/providers/imap.py:616
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“Flag FETCH failure silently drops flag deltas while MODSEQ checkpoint advances”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：raise on FETCH failure (or return a failure marker) so delta aborts without advancing modseq; never advance modseq past UIDs whose flags were not applied

### A14. Checksum is fetched from the same origin as the binary (TOFU, no pinned hash) （预存， round-1 Critical partially fixed)

- 来源：bundle_cross_validation, bundle_desktop_scripts, bundle_regression
- 位置：scripts/fetch-pg-binaries.sh:44, :48
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“Checksum is fetched from the same origin as the binary (TOFU, no pinned hash) （预存， round-1 Critical partially fixed)”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：commit per-version/per-target SHA-256 values in the repo (or a signed manifest) and require them by default; treat same-origin sidecars only as a fallback warning

### A15. （预存）setReadOptimistic fires one POST per message with unbounded fan-out

- 来源：bundle_cross_validation, bundle_frontend_state, bundle_regression
- 位置：src/frontend/src/api/queries.ts:281
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“（预存）setReadOptimistic fires one POST per message with unbounded fan-out”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：chunk targets (e.g. 25–50 concurrent max) or route bulk selections through postMailCoreMarkAllRead, and abort remaining chunks on first hard failure.

### A16. mark_all_messages_read loads the entire matching scope into memory and enqueues per-message remote ops in one transaction

- 来源：bundle_cross_validation, bundle_mc_api_app
- 位置：src/mail_core/mail/application/mutations.py:292
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“mark_all_messages_read loads the entire matching scope into memory and enqueues per-message remote ops in one transaction”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：process in bounded batches with per-batch commits (or a single bulk UPDATE + one coalesced remote op per account/folder), and cap or chunk the scope

### A17. One failed metadata hydration poisons the whole page and wedges the sync cursor

- 来源：bundle_cross_validation, bundle_mc_providers_sync
- 位置：src/mail_core/providers/gmail.py:236
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“One failed metadata hydration poisons the whole page and wedges the sync cursor”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：skip-and-record per-message hydration failures (exclude the id, surface a partial-page signal) instead of failing the page, or route repeated per-id 404s to reconcile

### A18. （预存）Image default CMD trusts all proxies

- 来源：bundle_cross_validation, bundle_root_ci
- 位置：Dockerfile.mail-core:25
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“（预存）Image default CMD trusts all proxies”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：drop `--forwarded-allow-ips "*"` from the image CMD (default to 127.0.0.1) and require operators to pass an explicit proxy IP/CIDR.

### A19. Chaos guard validates only the database name, not the host or ownership

- 来源：bundle_cross_validation, bundle_desktop_scripts
- 位置：scripts/mail-core-chaos-lease.sh:16
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“Chaos guard validates only the database name, not the host or ownership”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：require host 127.0.0.1/localhost, reject query strings, and verify the target is the dedicated test instance before migrating

### A20. Fan-out blocks the LISTEN thread up to 0.5s per subscriber per event while holding outbox row locks

- 来源：bundle_cross_validation, bundle_mc_api_app
- 位置：src/mail_core/realtime/dispatcher.py:116
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“Fan-out blocks the LISTEN thread up to 0.5s per subscriber per event while holding outbox row locks”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：drop the future wait (fire-and-forget `call_soon_threadsafe` with queue-full isolation only), or release row locks before fan-out and mark dispatched in a second short transaction

### A21. Reconcile holds the lease with no heartbeat during an unbounded full remote scan

- 来源：bundle_cross_validation, bundle_mc_providers_sync
- 位置：src/mail_core/sync/reconcile.py:69
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“Reconcile holds the lease with no heartbeat during an unbounded full remote scan”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：heartbeat between provider pages (requires a paged reconcile contract) or raise the reconcile lease TTL and re-assert/renew before applying deletes in bounded batches

### A22. Restore-onto-source guard is a redacted-string URL comparison and is bypassable （预存）

- 来源：bundle_cross_validation, bundle_mc_data_crypto
- 位置：src/mail_core/backup/package.py:711
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“Restore-onto-source guard is a redacted-string URL comparison and is bypassable （预存）”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：parse both URLs and compare normalized (scheme-normalized host, effective port, database, user) tuples, and make the source URL a required parameter

### A23. reserve_quota hard-limit check is check-then-insert with no lock, despite "Atomically reserve" docstring

- 来源：bundle_cross_validation, bundle_mc_data_crypto
- 位置：src/mail_core/blobs/quota.py:98
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“reserve_quota hard-limit check is check-then-insert with no lock, despite "Atomically reserve" docstring”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：take a transaction-scoped advisory lock (or a singleton quota row `FOR UPDATE`) around the check-and-insert

### A24. Provider remote_state (new remote_id after MOVE) is discarded, breaking message identity

- 来源：bundle_cross_validation, bundle_mc_providers_sync
- 位置：src/mail_core/sync/remote_push.py:219
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“Provider remote_state (new remote_id after MOVE) is discarded, breaking message identity”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：persist remote_state id/folder mapping back onto Message/MessageLocation on successful move/trash, or explicitly re-key the local row before marking the op DONE

### A25. pg_restore exit code 1 without FATAL/error text is reported as a successful restore （预存）

- 来源：bundle_cross_validation, bundle_mc_data_crypto
- 位置：src/mail_core/backup/package.py:820
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“pg_restore exit code 1 without FATAL/error text is reported as a successful restore （预存）”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：treat any non-zero pg_restore exit as failure unless an explicit allowlist of benign messages matches

### A26. MIME blob file is published before the digest lock is taken, leaving a GC unlink race

- 来源：bundle_cross_validation, bundle_mc_data_crypto
- 位置：src/mail_core/blobs/archive.py:760
- 优先级：HIGH
- 详细判断理由：审阅在此处复核到“MIME blob file is published before the digest lock is taken, leaving a GC unlink race”；问题影响安全边界、数据完整性、核心同步或发布可靠性，修复范围明确且不需要产品取舍，采纳。
- 修复说明：acquire the digest advisory lock in a transaction held across `put` + row insertion for the MIME blob, as done for attachments

### A27. （预存） Dead relative link to an archived task spec

- 来源：bundle_docs_live
- 位置：docs/specs/mail_sync_and_storage.md:65
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存） Dead relative link to an archived task spec”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：point the link to the archive path.

### A28. `className="spin"` has no CSS definition anywhere; three loading spinners never rotate （预存）

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/MessageList.tsx:660
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“`className="spin"` has no CSS definition anywhere; three loading spinners never rotate （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：define a shared `.spin { animation: settings-spin 1s linear infinite }` (respecting prefers-reduced-motion) or switch all three sites to the existing `settings-spin` class

### A29. Migration silently caps retained messages at the 200 most recent rows

- 来源：bundle_desktop_scripts
- 位置：scripts/migrate_from_legacy_db.py:142
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Migration silently caps retained messages at the 200 most recent rows”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：remove the cap (or add an explicit --limit/--sample flag), and always print how many legacy rows existed vs migrated

### A30. （预存） Live spec AC-002 is superseded but still marked done/current

- 来源：bundle_docs_live
- 位置：docs/specs/inbox_ui_and_search.md:27
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存） Live spec AC-002 is superseded but still marked done/current”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：rewrite AC-002 to the 50-per-page IntersectionObserver behavior or move the stale AC to the archive with a superseded note.

### A31. （预存） Conflicting test baselines accumulated as session residue in one live blueprint

- 来源：bundle_docs_live
- 位置：docs/blueprint/testing.md:279
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存） Conflicting test baselines accumulated as session residue in one live blueprint”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：keep one dated baseline table, move per-task historical results into the task archives, and date-stamp every count retained.

### A32. （预存） Domain glossary names a database table that does not exist

- 来源：bundle_docs_live
- 位置：docs/blueprint/domain.md:21
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存） Domain glossary names a database table that does not exist”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：change the cell to `outbox`.

### A33. tsconfig.node.json is still non-strict （预存， round-1/2 finding persists)

- 来源：bundle_frontend_ui, bundle_regression
- 位置：src/frontend/tsconfig.node.json:1, :2
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“tsconfig.node.json is still non-strict （预存， round-1/2 finding persists)”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add `"strict": true` to tsconfig.node.json compilerOptions and fix any fallout in vite.config.ts/playwright.config.ts

### A34. Reader toolbar buttons have their keyboard focus indicator explicitly removed （预存， 2026-10-23)

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/design-system/tokens.css:1335
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Reader toolbar buttons have their keyboard focus indicator explicitly removed （预存， 2026-10-23)”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：delete the outline/box-shadow suppression or replace it with a token-based outline/background that remains visible in both themes

### A35. （预存）Dark design tokens drifted from the shipped tokens.css

- 来源：bundle_root_ci
- 位置：assets/DESIGN.md:13
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）Dark design tokens drifted from the shipped tokens.css”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：regenerate one side from the other and add the existing css:check-style gate for DESIGN.md values.

### A36. （预存） Desktop guide repeats the false "permissions all denied" claim

- 来源：bundle_docs_live
- 位置：docs/guides/desktop.md:93
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存） Desktop guide repeats the false "permissions all denied" claim”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：amend step 2 to name the single clipboard exception and its trust conditions.

### A37. （预存） Skill doc teaches the same nonexistent inbox filter parameter

- 来源：bundle_docs_live
- 位置：docs/skills/kkmail/SKILL.md:128
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存） Skill doc teaches the same nonexistent inbox filter parameter”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：change the example to `?limit=50&is_read=false` and add the `is_flagged=true` form.

### A38. （预存） CLI renders unknown (null) read state as unread, violating the unknown-status contract

- 来源：bundle_docs_live
- 位置：docs/skills/kkmail/scripts/kkmail_cli.py:552
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存） CLI renders unknown (null) read state as unread, violating the unknown-status contract”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：render three states (read / unread / unknown "-") in list and search, and print "-" when `total_unread` is null.

### A39. （预存） Live spec contradicts itself on sidebar collapse behavior

- 来源：bundle_docs_live
- 位置：docs/specs/inbox_ui_and_search.md:31
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存） Live spec contradicts itself on sidebar collapse behavior”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：delete or rewrite AC-006 to the t032 full-removal semantics.

### A40. （预存） Desktop guide cites section anchors that do not exist in the live architecture doc

- 来源：bundle_docs_live
- 位置：docs/guides/desktop.md:3
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存） Desktop guide cites section anchors that do not exist in the live architecture doc”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：cite the live architecture section by heading name (or point explicitly to `docs/archive/legacy_architecture/mail-core-architecture.md` §4.3).

### A41. （预存）Diagnostics context is stored and exported completely unredacted, and redact() misses JSON-style secrets

- 来源：bundle_frontend_state
- 位置：src/frontend/src/lib/diagnostics.ts:44
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）Diagnostics context is stored and exported completely unredacted, and redact() misses JSON-style secrets”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：deep-redact context objects by key name before storage and extend redact() to JSON colon forms.

### A42. （预存）SSE reconnect is a fixed 2s interval with no backoff/jitter, contradicting the module doc

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/sseStream.ts:102
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）SSE reconnect is a fixed 2s interval with no backoff/jitter, contradicting the module doc”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：exponential backoff with jitter (e.g. 1s→30s cap, reset on successful open) and honor the SSE `retry:` field.

### A43. （预存）Dead second SSE implementation (EventSource) duplicates the live fetch-stream one with weaker semantics

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/mailCore.ts:188
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）Dead second SSE implementation (EventSource) duplicates the live fetch-stream one with weaker semantics”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：delete subscribeMailCoreEvents + MAIL_CORE_EVENTS (or re-export the stream implementation) and move its tests to sseStream.

### A44. （预存）Tested CSS-token implementation is not the one that gates: validateCssTokens (TS) is exercised only by its own test, while `npm test` runs a hand-cloned reimplementation in scripts/check_css_tokens.mjs

- 来源：bundle_frontend_state
- 位置：src/frontend/src/lib/checkCssTokens.ts:44
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）Tested CSS-token implementation is not the one that gates: validateCssTokens (TS) is exercised only by its own test, while `npm test` runs a hand-cloned reimplementation in scripts/check_css_tokens.mjs”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：make the .mjs gate import the compiled TS (or delete the TS copy and test the .mjs directly) so one implementation is both tested and gating.

### A45. No code splitting: login screen downloads the entire app including Settings, DOMPurify and all 21 brand icons

- 来源：bundle_frontend_ui
- 位置：src/frontend/vite.config.ts:8
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“No code splitting: login screen downloads the entire app including Settings, DOMPurify and all 21 brand icons”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：`React.lazy` the Settings page and UiReferenceOverlay (both off the first-paint path) and verify the emitted chunks in `vite build` output

### A46. LoginPage tests cover only the hint text; the credential submit flow is untested

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/LoginPage.test.tsx:14
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“LoginPage tests cover only the hint text; the credential submit flow is untested”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add tests stubbing `api.login` for success, rejection with a server message, and double-submit while loading

### A47. /api/mail/stats silently ignores folder_role unless group_id is given

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/mail.py:210
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“/api/mail/stats silently ignores folder_role unless group_id is given”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：pass folder_role through to the global query (parameterize the role join like `query_group_inbox_stats`) or reject the parameter when no group_id is present

### A48. HTTP layer violates the documented "routes call the application layer only" boundary

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/mail.py:21
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“HTTP layer violates the documented "routes call the application layer only" boundary”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：move the detail-nudge and sync-body orchestration into `mail.application` functions and expose a public lock helper from `accounts.service`

### A49. （预存）All GitHub Actions pinned to mutable tags, not SHAs

- 来源：bundle_root_ci
- 位置：.github/workflows/ci.yml:22
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）All GitHub Actions pinned to mutable tags, not SHAs”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：pin every action to a full commit SHA with a version comment and let Dependabot/Renovate bump them.

### A50. （预存）POSTGRES_PASSWORD interpolated into DATABASE_URL without URL-encoding

- 来源：bundle_root_ci
- 位置：docker-compose.mail-core.yml:52
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）POSTGRES_PASSWORD interpolated into DATABASE_URL without URL-encoding”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：document the hex/base64url-only constraint at the interpolation site or pass the password via a separate env var assembled in code.

### A51. （预存）CI tests Python 3.12 while the shipped image runs Python 3.13

- 来源：bundle_root_ci
- 位置：.github/workflows/ci.yml:124
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）CI tests Python 3.12 while the shipped image runs Python 3.13”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：align CI to 3.13 (or add a 3.12+3.13 matrix) matching the Dockerfile.

### A52. （预存）Unpinned `pip install uv` and ad-hoc dependency installs in CI

- 来源：bundle_root_ci
- 位置：.github/workflows/ci.yml:31
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）Unpinned `pip install uv` and ad-hoc dependency installs in CI”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：pin uv (e.g. astral-sh/setup-uv with an exact version) and install test deps from a locked/pinned requirements file.

### A53. Archive safety check inspects member names only, symlink/hardlink members escape extraction

- 来源：bundle_desktop_scripts, bundle_regression
- 位置：scripts/fetch-pg-binaries.sh:72, :83
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Archive safety check inspects member names only, symlink/hardlink members escape extraction”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：reject link members (inspect `tar -tvzf` type flags / zip external attrs) or extract with a no-symlink-follow tool and verify the full extracted tree stays under EXTRACT_DIR

### A54. Changing KKMAIL_PG_PORT after first init is silently ignored by the running cluster

- 来源：bundle_desktop_scripts
- 位置：src/desktop/postgresManager.js:247
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Changing KKMAIL_PG_PORT after first init is silently ignored by the running cluster”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：on every start, reconcile the managed port/listen lines in postgresql.conf with this.port (or detect the mismatch and error with the configured-vs-actual ports)

### A55. Script pip-installs unpinned requirements into the selected interpreter at run time

- 来源：bundle_desktop_scripts
- 位置：scripts/mail-core-chaos-lease.sh:20
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Script pip-installs unpinned requirements into the selected interpreter at run time”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：remove the install step (follow run-mail-core-tests.sh: fail with instructions when the venv/deps are missing) or install with --require-hashes into a verified venv

### A56. Test role/database are created before the try/finally that cleans them up

- 来源：bundle_desktop_scripts
- 位置：scripts/run_full_stack_e2e.py:92
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Test role/database are created before the try/finally that cleans them up”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：move the try: to immediately after engine creation and make the finally tolerant of partially created resources

### A57. 'pack:linux:with-pg' script does not fetch or verify PostgreSQL

- 来源：bundle_desktop_scripts
- 位置：src/desktop/package.json:19
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“'pack:linux:with-pg' script does not fetch or verify PostgreSQL”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：make the with-pg variant run the fetch script (with checksum verification) and fail if vendor/pgsql/bin/pg_ctl is absent afterwards

### A58. （预存） `health` command demands credentials for a public endpoint

- 来源：bundle_docs_live
- 位置：docs/skills/kkmail/scripts/kkmail_cli.py:324
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存） `health` command demands credentials for a public endpoint”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：let `health()` (and only it) bypass the login gate and call the opener directly.

### A59. （预存） "Backup key must differ from blob key" is documented as a system property but never enforced

- 来源：bundle_docs_live
- 位置：docs/guides/security.md:25
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存） "Backup key must differ from blob key" is documented as a system property but never enforced”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：either add a startup/backup-time equality check that rejects identical keys, or downgrade the doc wording to an unenforced operational recommendation.

### A60. （预存）CSRF token fetch swallows timeouts/network errors and misreports them as a login problem

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/client.ts:89
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）CSRF token fetch swallows timeouts/network errors and misreports them as a login problem”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：propagate a distinct timeout/network error from fetchCsrfToken and only claim re-login for 401.

### A61. （预存）Throttled invalidator refetches far more than message lists: invalidateQueries() matches every query under the prefix

- 来源：bundle_frontend_state
- 位置：src/frontend/src/hooks/useMailCoreRealtime.ts:53
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）Throttled invalidator refetches far more than message lists: invalidateQueries({queryKey:['mail-core']}) matches every query under the prefix”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：invalidate with the isMailListQueryKey predicate for list events and target stats keys only for folder.stats_updated/sync.completed.

### A62. Lint cannot catch effect-dependency or set-state-in-effect bugs

- 来源：bundle_frontend_ui
- 位置：src/frontend/.oxlintrc.json:7
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Lint cannot catch effect-dependency or set-state-in-effect bugs”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：enable `react/exhaustive-deps` as error and re-enable `react/set-state-in-effect` (or document per-site suppressions)

### A63. Mobile sidebar is `role="dialog" aria-modal="true"` but has no focus trap or initial focus （预存）

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/Sidebar.tsx:792
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Mobile sidebar is `role="dialog" aria-modal="true"` but has no focus trap or initial focus （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：on drawer open, focus the first nav control and trap Tab within the aside (or drop aria-modal and mark the background `inert`)

### A64. Every HTML body is sanitized and DOM-parsed at least twice per render cycle （预存， 2026-10-22)

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/MessageReader.tsx:96
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Every HTML body is sanitized and DOM-parsed at least twice per render cycle （预存， 2026-10-22)”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：compute classification once and pass it into buildMailSrcdoc (extend MailSrcdocOptions with a precomputed classification), memoizing the sanitized HTML

### A65. SSE slot-acquisition race returns an empty 200 stream instead of 503

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/sse.py:178
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“SSE slot-acquisition race returns an empty 200 stream instead of 503”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：acquire the slot in the endpoint body before constructing the StreamingResponse and return the 503 JSON there on failure

### A66. Account creation maps every exception to 400 with the raw exception string

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/accounts.py:212
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Account creation maps every exception to 400 with the raw exception string”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：map known domain errors explicitly, log the rest with `safe_error` and return a generic 500 detail

### A67. Events with no local subscribers are never marked dispatched, contradicting the docstring and growing the outbox

- 来源：bundle_mc_api_app
- 位置：src/mail_core/realtime/dispatcher.py:145
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Events with no local subscribers are never marked dispatched, contradicting the docstring and growing the outbox”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：align code and doc — have the listener call `dispatch_once(require_subscribers=True)` (skip) or explicitly drain-mark when this process owns dispatch, so undispatched state means "not yet delivered" by design

### A68. Initial-sync enqueue failures on account create/update are swallowed with no log

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/accounts.py:201
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Initial-sync enqueue failures on account create/update are swallowed with no log”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：log the failure with account id via `safe_error` and/or record a durable retry (outbox/job) instead of dropping it

### A69. Follow-up scheduling test never asserts run_after, hiding the broken delay path

- 来源：bundle_mc_api_app
- 位置：tests/mail_core/test_worker_loop.py:339
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Follow-up scheduling test never asserts run_after, hiding the broken delay path”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：assert `kwargs["run_after"] == datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)` in that test

### A70. Restore stub guard is dead code: compares method to "stub" but the writer emits "sql_stub" （预存）

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/backup/package.py:762
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Restore stub guard is dead code: compares method to "stub" but the writer emits "sql_stub" （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：compare against `"sql_stub"` (share the constant) so restore's own defense-in-depth works if verify is ever bypassed

### A71. Gmail metadata scan is N+1: one messages.get per listed message, no batch endpoint

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/gmail.py:228
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Gmail metadata scan is N+1: one messages.get per listed message, no batch endpoint”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：use the Gmail batch API (or at least concurrent bounded fan-out with a shared rate limiter) for metadata hydration

### A72. （预存）Design system specifies send/compose flows the product scope forbids

- 来源：bundle_root_ci
- 位置：assets/DESIGN.md:411
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）Design system specifies send/compose flows the product scope forbids”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：mark compose/send sections explicitly as non-shipped visual reference or remove the Send/Save-Draft requirements.

### A73. （预存）"Backup key MUST differ from blob key" is documented but never enforced

- 来源：bundle_root_ci
- 位置：docker-compose.mail-core.yml:69
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）"Backup key MUST differ from blob key" is documented but never enforced”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：fail startup/backup when the backup key equals any blob key version.

### A74. Registering an uncaughtException handler that only logs suppresses Node's default exit

- 来源：bundle_desktop_scripts
- 位置：src/desktop/desktopLog.js:142
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Registering an uncaughtException handler that only logs suppresses Node's default exit”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：after logging and flushing, re-raise/exit (e.g. schedule app.quit()/process.exit(1)) from the uncaughtException handler

### A75. E2E app connects as the postgres superuser instead of the created owner/app role

- 来源：bundle_desktop_scripts
- 位置：scripts/run_full_stack_e2e.py:83
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“E2E app connects as the postgres superuser instead of the created owner/app role”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：create a LOGIN app role with the run password, use it for app_url_obj, and reserve the superuser URL for admin/DDL steps only

### A76. Permission check handler defaults isMainFrame to true when details are missing

- 来源：bundle_desktop_scripts
- 位置：src/desktop/hardening.js:80
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Permission check handler defaults isMainFrame to true when details are missing”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：default isMainFrame to false in the check handler as well; allow only on an explicit true

### A77. Drill claims to ensure backup key differs from blob key but never checks it

- 来源：bundle_desktop_scripts
- 位置：scripts/mail-core-backup-restore-drill.sh:110
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Drill claims to ensure backup key differs from blob key but never checks it”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：after defaulting, compare the two values and exit 2 if they are equal

### A78. （预存）setReadOptimistic failure-revert clobbers interleaved state with a stale captured prior value

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/queries.ts:285
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）setReadOptimistic failure-revert clobbers interleaved state with a stale captured prior value”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：revert only if the current cached value still equals the optimistic value, otherwise invalidate the list queries instead of patching.

### A79. （预存）markReadOptimistic does a full cache scan + sort per target item (O(targets × queries × items))

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/queries.ts:276
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）markReadOptimistic does a full cache scan + sort per target item (O(targets × queries × items))”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：build a single key→item index over the cache once per setReadOptimistic call and look targets up in it.

### A80. `aria-selected` on a plain `<article>` and a nested interactive checkbox break ARIA semantics （预存）

- 来源：bundle_frontend_ui, bundle_regression
- 位置：src/frontend/src/components/MessageList.tsx:586, :590
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“`aria-selected` on a plain `<article>` and a nested interactive checkbox break ARIA semantics （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：give the list `role="listbox"`/rows `role="option"` (or remove aria-selected and expose selection via the checkbox only) and ensure the inner button does not trigger row activation from keyboard

### A81. MutationObserver re-scans the whole DOM on every mutation while the overlay is active （预存， 2026-10-23)

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/UiReferenceOverlay.tsx:91
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“MutationObserver re-scans the whole DOM on every mutation while the overlay is active （预存， 2026-10-23)”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：debounce/coalesce scans via rAF (as done for scroll), skip scans when the mutation targets the overlay's own container, and bail out when badge positions are unchanged

### A82. GET message detail mutates state and enqueues jobs (unsafe side effect on a safe, CSRF-exempt method)

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/mail.py:331
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“GET message detail mutates state and enqueues jobs (unsafe side effect on a safe, CSRF-exempt method)”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：make GET pure; move the priority boost to the explicit POST sync-body endpoint or a dedicated POST nudge that the reader UI calls

### A83. Full reclaim/prune/resume sweep runs on every worker tick

- 来源：bundle_mc_api_app
- 位置：src/mail_core/worker/main.py:92
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Full reclaim/prune/resume sweep runs on every worker tick”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：run the sweep on a separate cadence (e.g. every N ticks or every 60s) inside `run()`, not per claim batch

### A84. MAIL_CORE_LOG_LEVEL is accepted by the desktop launcher but never read

- 来源：bundle_mc_api_app
- 位置：src/mail_core/logging_config.py:54
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“MAIL_CORE_LOG_LEVEL is accepted by the desktop launcher but never read”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：read `MAIL_CORE_LOG_LEVEL` in `configure_logging` (invalid value → INFO with a warning) and document it in `src/mail_core/README.md`

### A85. "Primary" message location is chosen without ORDER BY

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/mutations.py:33
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“"Primary" message location is chosen without ORDER BY”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：order locations deterministically (e.g. by folder role priority then folder_id) in one shared helper used by all mutations

### A86. read_session performs a database query on every authenticated request

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/security/auth.py:342
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“read_session performs a database query on every authenticated request”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：cache the epoch in-process with a short TTL / invalidate on password change, or embed epoch checks only at login and mutation points as the spec's cost model implies

### A87. The only end-to-end restore test is skipped without a live DB and no offline test exercises restore_backup_package's success path

- 来源：bundle_mc_data_crypto
- 位置：tests/mail_core/test_backup_restore_drill_live.py:27
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“The only end-to-end restore test is skipped without a live DB and no offline test exercises restore_backup_package's success path”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add an offline restore test with a fake pg_restore/pg_dump on PATH (pattern already used in test_backup_package.py:405) covering sealed and plain packages

### A88. MODSEQ delta swallows all exceptions including CursorInvalidError, then fallback stamps modseq

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/imap.py:736
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“MODSEQ delta swallows all exceptions including CursorInvalidError, then fallback stamps modseq”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：re-raise CursorInvalidError explicitly, log other failures, and do not stamp modseq=highest unless the MODSEQ search actually succeeded

### A89. Reassigning a message to a different thread leaves a stale ThreadMessage row

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/threading/rules.py:202
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Reassigning a message to a different thread leaves a stale ThreadMessage row”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：delete ThreadMessage rows for this message under other thread ids when thread_id changes

### A90. upsert_messages flushes per created message and search-indexes with 3 extra queries per message

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/metadata.py:102
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“upsert_messages flushes per created message and search-indexes with 3 extra queries per message”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：batch-create with a single flush per page and bulk-load MessageBody/MessageSearch rows for the page's ids before indexing

### A91. \_apply_flag_patches does one SELECT per flag change

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/delta.py:61
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“\_apply_flag_patches does one SELECT per flag change”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：bulk-load all messages for the page's remote_ids once and index them by remote_id before patching

### A92. Rate-limited remote ops requeue forever with no attempt cap

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/remote_push.py:265
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Rate-limited remote ops requeue forever with no attempt cap”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：apply the same attempts cap (or a separate larger cap with dead-letter) to rate-limited retries

### A93. Migration target is implicit and unguarded, source path is hardcoded

- 来源：bundle_desktop_scripts
- 位置：scripts/migrate_from_legacy_db.py:262
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Migration target is implicit and unguarded, source path is hardcoded”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add required explicit --source and --target-url arguments, print both, and require a --yes flag after showing the target host/db

### A94. RotatingLogStream silently stalls and grows an unbounded queue when the fd is unavailable

- 来源：bundle_desktop_scripts
- 位置：src/desktop/logRotation.js:110
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“RotatingLogStream silently stalls and grows an unbounded queue when the fd is unavailable”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：on fd-null, drop queued chunks with an error callback (and surface lastError), cap the queue length, and notify drain waiters with the error

### A95. Docker success is reported without any IMAP readiness check and all docker errors are swallowed

- 来源：bundle_desktop_scripts
- 位置：scripts/start-mail-core-imap.sh:20
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Docker success is reported without any IMAP readiness check and all docker errors are swallowed”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：keep stderr visible on the final failure path and poll the IMAP port (banner/TCP connect with timeout) before exiting 0

### A96. Isolated slow consumers become zombie SSE connections

- 来源：bundle_mc_api_app
- 位置：src/mail_core/realtime/dispatcher.py:52
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Isolated slow consumers become zombie SSE connections”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：signal isolation into the stream itself (e.g. close the queue with a sentinel that ends the generator after the hint) so the client reconnects and replays

### A97. mark_unreferenced_blobs loads every MessageBlob row into memory on each GC run

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/blobs/gc.py:53
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“mark_unreferenced_blobs loads every MessageBlob row into memory on each GC run”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：page the reconciliation in id batches (e.g. 1000 rows) or do the ref_count/gc_eligible_at reconciliation as set-based UPDATE statements

### A98. Every metadata page re-runs a range SEARCH and transfers the full remaining UID set

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/imap.py:493
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Every metadata page re-runs a range SEARCH and transfers the full remaining UID set”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：cache the UID list across pages within a scan session, or page with server-side UID sets computed from a single SEARCH plus cursor arithmetic on counts

### A99. Threading runs only for newly created messages on the metadata path, fragmenting Gmail threads

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/metadata.py:178
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Threading runs only for newly created messages on the metadata path, fragmenting Gmail threads”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：run threading assignment for created messages whose parent may arrive later by re-checking children when a parent is created, or thread on any outcome carrying threading headers in both paths

### A100. Folder discovery never retires remote-deleted folders and enqueues undeduped metadata jobs

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/engine.py:186
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Folder discovery never retires remote-deleted folders and enqueues undeduped metadata jobs”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：mark local folders missing from a complete remote listing as paused/removed, and pass dedupe_key=f"metadata:{account_id}:{folder_id}" on discovery enqueues

### A101. Lease-busy and provider-error retries enqueue jobs without dedupe_key

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/delta.py:278
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Lease-busy and provider-error retries enqueue jobs without dedupe_key”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：use the same dedupe_key=f"delta:{account_id}:{folder_id}" on all followup enqueues in sync_folder_delta (and the metadata equivalent in engine.py)

### A102. Transient-error detection matches raw substrings '429'/'500' anywhere in the error text

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/remote_push.py:61
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Transient-error detection matches raw substrings '429'/'500' anywhere in the error text”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：classify on structured status codes only; restrict text matching to anchored phrases from known provider error shapes

### A103. Metadata cursor advances past UIDs whose FETCH blobs came back missing

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/imap.py:543
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Metadata cursor advances past UIDs whose FETCH blobs came back missing”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：derive next_uid from the last UID actually returned, or record the gap UIDs for a follow-up targeted fetch before marking the scan complete

### A104. （预存）No stale-connection watchdog: a silently dead SSE stream is never detected

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/sseStream.ts:167
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存）No stale-connection watchdog: a silently dead SSE stream is never detected”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：track last-event/keepalive time and abort+reconnect when no bytes arrive within e.g. 2× the server keepalive interval.

### A105. sync-body enqueues work the archive runner can never claim for failed/paused/exhausted messages

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/mail.py:387
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“sync-body enqueues work the archive runner can never claim for failed/paused/exhausted messages”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：transition failed/paused rows back to `archive_pending` via `apply_transition` (and reset/handle retry_count) when the user explicitly requests sync-body, or return 409 with the blocking state

### A106. Poll backoff is driven by handled-count, so a batch of failing jobs backs off the whole queue

- 来源：bundle_mc_api_app
- 位置：src/mail_core/worker/main.py:156
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Poll backoff is driven by handled-count, so a batch of failing jobs backs off the whole queue”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：base the delay on claimed count as well (claimed > 0 → poll at base interval regardless of success), reserving backoff for genuinely empty claims

### A107. Every log line is truncated to 4000 chars after formatting, cutting off exception root causes

- 来源：bundle_mc_api_app
- 位置：src/mail_core/logging_config.py:49
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Every log line is truncated to 4000 chars after formatting, cutting off exception root causes”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：redact without a hard total-length cap, or truncate the message portion while preserving the last lines of the traceback

### A108. Pre-existing secret files keep whatever permissions they already have

- 来源：bundle_mc_api_app
- 位置：src/mail_core/runtime/bootstrap.py:25
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Pre-existing secret files keep whatever permissions they already have”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：`os.chmod(path, 0o600)` (best-effort) on the existing-file path as well, and warn if tightening fails

### A109. List body previews load full message bodies for the whole page

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/queries.py:128
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“List body previews load full message bodies for the whole page”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：truncate in SQL (e.g. `left(text_html, N)`) or store a bounded preview column at parse time

### A110. Listener stop/start can silently leave realtime dead

- 来源：bundle_mc_api_app
- 位置：src/mail_core/realtime/listener.py:65
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Listener stop/start can silently leave realtime dead”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：make `stop()` interruptible (close the connection / wait on `_stop` instead of sleeping) and have `start()` wait for the old thread to die before spawning a new one

### A111. No test covers what /health discloses

- 来源：bundle_mc_api_app
- 位置：tests/mail_core/test_api_health.py:6
- 优先级：MEDIUM
- 详细判断理由：/health 会按现行桌面握手契约回显每次启动的 instance token，startup.js 会校验该值。测试缺口属实，但断言 header 不得出现会与生产行为冲突；采纳覆盖真实握手契约的测试。
- 修复说明：设置 `KKMAIL_INSTANCE_TOKEN` 后请求未认证的 /health，断言 `X-Instance-Token` 与该值相等且响应 JSON 不含 token；清除变量后断言 header 不出现。

### A112. credential_edit change detection uses a shallow copy, so nested-dict mutations are silently dropped

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/accounts/credentials.py:305
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“credential_edit change detection uses a shallow copy, so nested-dict mutations are silently dropped”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：snapshot with `copy.deepcopy` or `json.loads(json.dumps(data))` before yielding

### A113. MAIL_CORE_BLOB_KEY_V1 silently overrides the JSON keyring's version-1 key

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/blobs/crypto.py:73
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“MAIL_CORE_BLOB_KEY_V1 silently overrides the JSON keyring's version-1 key”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：raise BlobCryptoError if both sources define version 1 with different bytes

### A114. acquire_blob_digest_lock swallows all exceptions, so blob publish/GC coordination fails open

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/blobs/quota.py:162
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“acquire_blob_digest_lock swallows all exceptions, so blob publish/GC coordination fails open”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：only swallow the non-PostgreSQL-dialect case; log and re-raise lock failures when the dialect is PostgreSQL

### A115. SSRF host check is TOCTOU-vulnerable via DNS rebinding （预存）

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/factory.py:59
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“SSRF host check is TOCTOU-vulnerable via DNS rebinding （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：resolve once, pin the validated IP for the connection (or re-validate the connected peer address), and reject names whose answers mix public and private records

### A116. delta_changes lacks the \\Noselect guard its sibling methods have

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/imap.py:654
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“delta_changes lacks the \\Noselect guard its sibling methods have”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：apply the same \_is_mailbox_noselect check in delta_changes and return an exhausted empty DeltaPage

### A117. Unconverged-intent query has no ordering, so a stale DONE intent can override a newer PENDING one

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/remote_push.py:398
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Unconverged-intent query has no ordering, so a stale DONE intent can override a newer PENDING one”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：order by updated_at/created_at ascending so the newest op wins, or keep only the max-updated_at op per (remote_id, field)

### A118. Job attempts are burned by claiming and reclaiming, not by real failures

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/jobs.py:149
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Job attempts are burned by claiming and reclaiming, not by real failures”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：track claim count separately from failure attempts, or increment attempts in fail_job instead of claim_jobs

### A119. Stale-claim reclaim (5 min) can requeue jobs that are still legitimately running

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/jobs.py:199
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Stale-claim reclaim (5 min) can requeue jobs that are still legitimately running”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add a locked_at heartbeat for long jobs (or raise/scope the reclaim window per job type) and document the contract for handlers

### A120. urllib_json_request retries non-idempotent POSTs on 503/504 and network errors

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/oauth.py:331
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“urllib_json_request retries non-idempotent POSTs on 503/504 and network errors”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：retry only idempotent methods (GET/HEAD) automatically; for POST require an idempotency check or surface an ambiguous-outcome error

### A121. Production provider code branches on a test-double response shape ('page' key)

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/gmail.py:219
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Production provider code branches on a test-double response shape ('page' key)”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：remove the 'page' shortcut from providers and make FixtureTransport return realistic wire-shaped JSON in tests

### A122. （预存） Upgrade guide's bare compose command may not restart the worker it promises

- 来源：bundle_docs_live
- 位置：docs/guides/upgrade.md:11
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“（预存） Upgrade guide's bare compose command may not restart the worker it promises”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：make upgrade.md use the explicit `up --build -d api worker` form from deployment.md (or state the required `--profile distributed`).

### A123. Initial login-hash write is racy across concurrent first starts

- 来源：bundle_mc_api_app, bundle_regression
- 位置：src/mail_core/runtime/bootstrap.py:28, :78
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Initial login-hash write is racy across concurrent first starts”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：create the hash with O_EXCL like `_read_or_create` and have losers re-read the winner's files, or take a data-dir lockfile for the whole bootstrap

### A124. Every search page pays a second full FTS count query

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/search.py:52
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Every search page pays a second full FTS count query”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：only compute total when offset == 0 (return `total=None`/cached afterwards) or use a window count on the id query

### A125. Credential store is resolved before the try block for every job type

- 来源：bundle_mc_api_app
- 位置：src/mail_core/worker/handlers.py:110
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Credential store is resolved before the try block for every job type”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：resolve the store lazily inside the branches that need it, or move the call inside the try

### A126. sync-all enqueues every account in one unbounded transaction

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/accounts.py:294
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“sync-all enqueues every account in one unbounded transaction”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：commit per page (or per account), cap/report progress asynchronously, and return a count plus a truncated/sampled id list

### A127. get_session_epoch writes an AuthCredential row on a read path

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/security/auth.py:275
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“get_session_epoch writes an AuthCredential row on a read path”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：create the epoch row only during bootstrap/password setup, and make the getter tolerate a missing row (return in-memory epoch) or use INSERT ... ON CONFLICT DO NOTHING

### A128. Fetch-timeout setting accepts infinity, which is then returned as the effective timeout

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/accounts/settings_store.py:77
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Fetch-timeout setting accepts infinity, which is then returned as the effective timeout”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：require `math.isfinite(timeout_val)` and an upper bound (e.g. 600s) on write and on read

### A129. create_account skips all connection/credential validation when config is falsy

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/accounts/service.py:47
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“create_account skips all connection/credential validation when config is falsy”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：validate unconditionally, passing `config or {}` and `require_credentials=credentials is not None`

### A130. create_backup_package defaults to a plaintext package when MAIL_CORE_BACKUP_KEY is unset

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/backup/package.py:312
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“create_backup_package defaults to a plaintext package when MAIL_CORE_BACKUP_KEY is unset”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：default `encrypt=None` to True in create_backup_package as well, requiring an explicit `encrypt=False` opt-in for plaintext

### A131. delta_changes holds its connection open while fetch_metadata_page opens a second one

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/imap.py:740
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“delta_changes holds its connection open while fetch_metadata_page opens a second one”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：reuse the already-selected connection for the nested fetch, or close/park c before paging metadata

### A132. get_unconverged_field_intents truncates remote_ids containing ':' when parsing entity_key

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/remote_push.py:415
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“get_unconverged_field_intents truncates remote_ids containing ':' when parsing entity_key”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：parse with rsplit(':', 1) after stripping the msg: prefix, or store remote_id in desired_state and match on that instead of parsing entity_key

### A133. Graph folder/message paging loops are unbounded

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/graph.py:113
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Graph folder/message paging loops are unbounded”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：cap total pages/items per call and detect repeated nextLink values

### A134. BearerTransport replays the original request after a forced 401 refresh

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/oauth.py:221
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“BearerTransport replays the original request after a forced 401 refresh”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：only auto-replay idempotent methods after 401; for writes, verify current remote state or return an ambiguous result

### A135. Key rotation re-encrypts and commits credential_secrets before any blob file is rotated

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/blobs/rotate.py:147
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Key rotation re-encrypts and commits credential_secrets before any blob file is rotated”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：rotate blobs first, secrets last, and document/enforce that old keys are retired only after a run reports `errors == []` and zero files on the old version

### A136. All API-key principals share one OAuth flow binding key

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/accounts/oauth_flow.py:103
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“All API-key principals share one OAuth flow binding key”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：bind to a digest of the presented API key, like the session branch does with the CSRF token

### A137. \_quote_mailbox does not strip CR/LF, enabling IMAP command injection via folder names

- 来源：bundle_mc_providers_sync, bundle_regression
- 位置：src/mail_core/providers/imap.py:196
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“\_quote_mailbox does not strip CR/LF, enabling IMAP command injection via folder names”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：reject or strip \\r and \\n (and other control chars) in \_quote_mailbox and in dest folder validation before any command is built

### A138. Delta coalescing drops flag changes carried only in meta.is_flagged

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/delta.py:123
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Delta coalescing drops flag changes carried only in meta.is_flagged”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：fall back to both meta.is_read and meta.is_flagged when flags is empty, in both the coalescer and \_apply_flag_patches

### A139. sync_account_folders duplicates its failure handling in nested and outer except blocks

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/engine.py:126
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“sync_account_folders duplicates its failure handling in nested and outer except blocks”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：collapse to a single failure path (handle list_folders errors in one place) and make release idempotent-safe by design rather than by exception

### A140. Device-code poll endpoint has no route-level pacing

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/oauth_routes.py:203
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Device-code poll endpoint has no route-level pacing”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：enforce a minimum poll interval per flow in the route/service response (e.g. 429 with Retry-After when polled faster than the device-code `interval`)

### A141. unlink_gc_paths deletes files with no DB safety check whenever the filename stem is not 64 chars

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/blobs/gc.py:181
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“unlink_gc_paths deletes files with no DB safety check whenever the filename stem is not 64 chars”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：derive paths via `BlobStore.path_for(digest)`/containment validation and fail closed for non-digest stems like the 64-char branch does

### A142. （预存） Documented reconcile job priority does not match code

- 来源：bundle_docs_live
- 位置：docs/blueprint/architecture.md:65
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存） Documented reconcile job priority does not match code”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：change 85 to 80.

### A143. （预存）Duplicated Playwright installs and duplicated OpenAPI check per CI run

- 来源：bundle_root_ci
- 位置：.github/workflows/ci.yml:134
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）Duplicated Playwright installs and duplicated OpenAPI check per CI run”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：drop the standalone openapi:check step and cache <local-path> across jobs.

### A144. Benchmark is Unix-only despite the repo's cross-platform desktop targets

- 来源：bundle_desktop_scripts
- 位置：scripts/benchmark_mailbox.py:18
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Benchmark is Unix-only despite the repo's cross-platform desktop targets”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：guard the import and fall back to a psutil-free RSS probe (or 0/unknown) on win32

### A145. Migrated messages lose their flagged state

- 来源：bundle_desktop_scripts
- 位置：scripts/migrate_from_legacy_db.py:187
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Migrated messages lose their flagged state”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：map the legacy flag column if present, otherwise record the loss in the migration report counts

### A146. Desktop 'npm test' silently skips oauth_integration.test.js

- 来源：bundle_desktop_scripts
- 位置：src/desktop/package.json:15
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Desktop 'npm test' silently skips oauth_integration.test.js”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add 'node oauth_integration.test.js' to the test script (or glob \*.test.js)

### A147. Password-reset Method 1 gives a wrong rationale for the restart step

- 来源：bundle_docs_live
- 位置：docs/guides/troubleshooting.md:50
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Password-reset Method 1 gives a wrong rationale for the restart step”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：drop the restart step or mark it optional/defensive and remove the cache rationale.

### A148. （预存） CLI silently strips whitespace from credentials

- 来源：bundle_docs_live
- 位置：docs/skills/kkmail/scripts/kkmail_cli.py:145
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存） CLI silently strips whitespace from credentials”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：do not strip the password/API key (strip only a trailing newline from env-sourced values, or nothing at all).

### A149. （预存） Token-gate script path does not resolve from the repo root

- 来源：bundle_docs_live
- 位置：docs/blueprint/conventions.md:17
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存） Token-gate script path does not resolve from the repo root”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：give the full path `src/frontend/scripts/check_css_tokens.mjs`.

### A150. General-settings validation is not scoped to the fields actually changed （预存， 2026-10-24)

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/SettingsModal.tsx:349
- 优先级：LOW
- 详细判断理由：审阅在此处确认“General-settings validation is not scoped to the fields actually changed （预存， 2026-10-24)”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：validate each field only when it is present in `patch`

### A151. A stats-only failure is reported to the user as "账户加载失败" （预存）

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/Sidebar.tsx:854
- 优先级：LOW
- 详细判断理由：审阅在此处确认“A stats-only failure is reported to the user as "账户加载失败" （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：separate the stats error into its own muted note (or suppress it when the per-account fallback produced data) and keep the alert for accounts/groups/layout only

### A152. Folder-tree load failure has no retry affordance （预存）

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/Sidebar.tsx:181
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Folder-tree load failure has no retry affordance （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：render a small retry button calling `foldersQuery.refetch()` in the error state

### A153. Hard-coded colors bypass the token system the file claims to enforce （预存）

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/design-system/tokens.css:1159
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Hard-coded colors bypass the token system the file claims to enforce （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：express these via existing tokens (var(--primary)/var(--on-primary)/color-mix) and extend scripts/check_css_tokens.mjs to flag raw hex outside the token declaration blocks

### A154. UI-reference registry has drifted from the DOM: ML14 describes a removed element, SB15 is missing

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/lib/uiReference.ts:49
- 优先级：LOW
- 详细判断理由：审阅在此处确认“UI-reference registry has drifted from the DOM: ML14 describes a removed element, SB15 is missing”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：delete ML14 (and other dead SB entries) and add SB15/SB16 descriptions, with a test that cross-checks registry keys against data-ui attributes found in components

### A155. Hardcoded CI test-Postgres password literal

- 来源：bundle_privacy_history, bundle_root_ci
- 位置：.github/workflows/ci.yml:146
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Hardcoded CI test-Postgres password literal”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：generate the password per run (e.g. $RANDOM/openssl) in the workflow instead of committing a fixed literal _(cross-bundle: privacy_history, root_ci)_

### A156. Hardcoded scheduled-drill test-Postgres password literal

- 来源：bundle_privacy_history, bundle_root_ci
- 位置：.github/workflows/scheduled.yml:32
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Hardcoded scheduled-drill test-Postgres password literal”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：generate per run as in ci.yml and remove the fixed literal _(cross-bundle: privacy_history, root_ci)_

### A157. （预存）Backend job's setup-node has no npm cache unlike the other Node jobs

- 来源：bundle_root_ci
- 位置：.github/workflows/ci.yml:127
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）Backend job's setup-node has no npm cache unlike the other Node jobs”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add the same cache + cache-dependency-path to the backend job.

### A158. （预存）postgres:16 referenced by mutable tag with no digest pin

- 来源：bundle_root_ci
- 位置：docker-compose.mail-core.yml:17
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）postgres:16 referenced by mutable tag with no digest pin”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：pin images by digest in the compose files and record the tested tags.

### A159. Groups are matched by name only, collapsing distinct legacy groups

- 来源：bundle_desktop_scripts
- 位置：scripts/migrate_from_legacy_db.py:295
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Groups are matched by name only, collapsing distinct legacy groups”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：match on the legacy id via a persisted mapping, or disambiguate by (name, sort_order/color) and warn on collision

### A160. Re-running the migration never updates existing accounts

- 来源：bundle_desktop_scripts
- 位置：scripts/migrate_from_legacy_db.py:374
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Re-running the migration never updates existing accounts”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：update the mutable fields on the existing row (or log each skipped field) so re-runs converge

### A161. External-URL allowlist permits plain http:

- 来源：bundle_desktop_scripts
- 位置：src/desktop/paths.js:26
- 优先级：LOW
- 详细判断理由：审阅在此处确认“External-URL allowlist permits plain http:”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：allow http: only for loopback, require https: for external hosts, and special-case the local app origin in the window-open handler

### A162. Drill misattributes every RuntimeError to a missing pg_dump

- 来源：bundle_desktop_scripts
- 位置：scripts/mail-core-backup-restore-drill.sh:131
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Drill misattributes every RuntimeError to a missing pg_dump”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：match on the dump-specific error (message/type from the backup package) and re-raise anything else

### A163. E2E blob directories are never cleaned up

- 来源：bundle_desktop_scripts
- 位置：scripts/run_full_stack_e2e.py:95
- 优先级：LOW
- 详细判断理由：审阅在此处确认“E2E blob directories are never cleaned up”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：shutil.rmtree(blob_dir, ignore_errors=True) in the finally block (behind a keep-artifacts flag if needed)

### A164. process 'exit' fallback cannot escalate to a hard kill

- 来源：bundle_desktop_scripts
- 位置：src/desktop/main.js:352
- 优先级：LOW
- 详细判断理由：审阅在此处确认“process 'exit' fallback cannot escalate to a hard kill”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：in the exit handler, synchronously SIGKILL the process group (process.kill(-pid, 'SIGKILL')) after the soft attempt

### A165. （预存） Duplicated authority: the UUID-as-capability rule is fully defined in three live docs

- 来源：bundle_docs_live
- 位置：docs/guides/security.md:13
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存） Duplicated authority: the UUID-as-capability rule is fully defined in three live docs”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：keep the full definition in security.md only and reduce conventions/decisions to one-line references.

### A166. （预存）Unhandled ApiError rejections are logged as "[object Object]"

- 来源：bundle_frontend_state
- 位置：src/frontend/src/lib/diagnostics.ts:96
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）Unhandled ApiError rejections are logged as "[object Object]"”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：make ApiError a real Error subclass (or extract status/code/message in the handler before String()).

### A167. `#oauth-return` hash is never cleared when there is no active OAuth flow, so Settings re-opens on later reloads

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/App.tsx:96
- 优先级：LOW
- 详细判断理由：审阅在此处确认“`#oauth-return` hash is never cleared when there is no active OAuth flow, so Settings re-opens on later reloads”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：clear the hash in App.tsx immediately after consuming it, regardless of flow state

### A168. Copy-feedback timers are never cleared and the boundary never auto-resets （预存）

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/ErrorBoundary.tsx:37
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Copy-feedback timers are never cleared and the boundary never auto-resets （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：store timer ids and clear them in componentWillUnmount; accept a `resetKey` prop (e.g. selected mail/view) that clears `error` when it changes

### A169. Sidebar hand-rolls a FolderStatsItem DTO instead of using the generated schema type （预存）

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/Sidebar.tsx:32
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Sidebar hand-rolls a FolderStatsItem DTO instead of using the generated schema type （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：delete the local interface, import `AccountFolderStatsItemOut`, and type `apiRequest<AccountFolderStatsOut>` like MessageList does

### A170. Keyboard-adjustable separator exposes no value to assistive tech

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/ColumnResize.tsx:51
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Keyboard-adjustable separator exposes no value to assistive tech”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add aria-valuemin/valuemax/valuenow driven by the current width (requires passing the value in as a prop) or switch to role="slider" with an aria-label naming the panel

### A171. After a save whose follow-up refresh fails, the dialog is permanently busy and cannot be resubmitted

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/settings_account_form.tsx:283
- 优先级：LOW
- 详细判断理由：审阅在此处确认“After a save whose follow-up refresh fails, the dialog is permanently busy and cannot be resubmitted”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：after the saved-refresh-failed branch, reset busy (the write already succeeded) so the user can close or re-save, keeping only the double-submit guard while a write is actually in flight

### A172. Lazy export map is incomplete, so the package's public API disagrees with its submodules

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/__init__.py:12
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Lazy export map is incomplete, so the package's public API disagrees with its submodules”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：complete the map (or generate it) and add a test that every public `*_app`/query/mutation function is reachable via the package

### A173. Retry-count documentation disagrees with the code

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/oauth.py:272
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Retry-count documentation disagrees with the code”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：align the docstring (and any runbook numbers) with the actual 4-attempt behavior or change the loop bounds

### A174. （预存）No timeout-minutes on any job in either workflow

- 来源：bundle_root_ci
- 位置：.github/workflows/ci.yml:17
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）No timeout-minutes on any job in either workflow”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：set per-job timeouts (e.g. 30 min CI jobs, 60 min drills).

### A175. （预存）api and postgres have no restart policy

- 来源：bundle_root_ci
- 位置：docker-compose.mail-core.yml:46
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）api and postgres have no restart policy”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add `restart: unless-stopped` to postgres and api.

### A176. （预存）Test images unpinned and test IMAP image tag is a bare local name

- 来源：bundle_root_ci
- 位置：config/test_pg_compose.yaml:4
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）Test images unpinned and test IMAP image tag is a bare local name”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：pin postgres by digest and stamp the dovecot image with the fixture's git revision.

### A177. （预存）Frontend build Node version differs between image and CI

- 来源：bundle_regression, bundle_root_ci
- 位置：Dockerfile.mail-core:2
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）Frontend build Node version differs between image and CI”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：align the Dockerfile frontend stage to node:22-alpine.

### A178. （预存）No container hardening on any compose service

- 来源：bundle_root_ci
- 位置：docker-compose.mail-core.yml:16
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）No container hardening on any compose service”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add no-new-privileges + cap_drop ALL to api/worker/migrate and document any postgres exception.

### A179. Instance token is passed to the backend as a command-line argument

- 来源：bundle_desktop_scripts
- 位置：src/desktop/main.js:133
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Instance token is passed to the backend as a command-line argument”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：pass the token only via the child env (already collected in baseExtras) and drop the argv form, or read it from a 0600 file

### A180. KKMAIL_PG_PASSWORD override is not persisted, so the next launch invents a different password

- 来源：bundle_desktop_scripts
- 位置：src/desktop/postgresManager.js:90
- 优先级：LOW
- 详细判断理由：审阅在此处确认“KKMAIL_PG_PASSWORD override is not persisted, so the next launch invents a different password”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：document the override as init-only and warn if a cluster already exists, or persist the override (0600) on first use

### A181. README misstates the scrubEnv boundary for PG variables

- 来源：bundle_desktop_scripts
- 位置：src/desktop/README.md:23
- 优先级：LOW
- 详细判断理由：审阅在此处确认“README misstates the scrubEnv boundary for PG variables”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：correct the table to say PG\* is passed only as explicit per-call extras, never inherited

### A182. （预存） Global `--json` pre-parse silently deletes the token anywhere in argv

- 来源：bundle_docs_live
- 位置：docs/skills/kkmail/scripts/kkmail_cli.py:431
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存） Global `--json` pre-parse silently deletes the token anywhere in argv”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：only honor `--json` before the subcommand, or register it as a proper argparse option on the top-level parser.

### A183. （预存）Caller headers are spread through a Record cast, silently dropping Headers-instance/array header forms

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/client.ts:168
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）Caller headers are spread through a Record cast, silently dropping Headers-instance/array header forms”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：normalize with `new Headers(extraHeaders)` and iterate entries.

### A184. （预存）Optimistic read/flag helpers ignore MutationResult.success=false on HTTP 200

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/queries.ts:283
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）Optimistic read/flag helpers ignore MutationResult.success=false on HTTP 200”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：treat `success === false` resolutions as failures (revert + collect the error) in setReadOptimistic/flagOptimistic.

### A185. （预存）previewText decodes only ' among numeric entities, leaking raw entities into list previews

- 来源：bundle_frontend_state
- 位置：src/frontend/src/lib/previewText.ts:15
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）previewText decodes only ' among numeric entities, leaking raw entities into list previews”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：decode numeric (decimal+hex) entities in stripHtmlToText before collapsing whitespace.

### A186. （预存）Unparsable dates are rendered as a raw slice of the backend string in the list

- 来源：bundle_frontend_state
- 位置：src/frontend/src/lib/listDate.ts:9
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）Unparsable dates are rendered as a raw slice of the backend string in the list”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：return '' (or a fixed '未知日期' label) for unparsable values, consistent with the null case.

### A187. Diagnostic UiReferenceOverlay ships in production and is mounted even on the unauthenticated login screen

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/App.tsx:125
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Diagnostic UiReferenceOverlay ships in production and is mounted even on the unauthenticated login screen”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：gate mounting behind a build-time flag (import.meta.env.DEV or an explicit VITE_UI_REFERENCE=1) so production bundles exclude it

### A188. Logout does not itself leave the workspace; it depends on a follow-on 401 to flip App auth state

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/SettingsModal.tsx:359
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Logout does not itself leave the workspace; it depends on a follow-on 401 to flip App auth state”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：have logout explicitly notify App (dispatch UNAUTHORIZED_EVENT or a dedicated callback/store flag) before/without relying on refetch

### A189. A failed session check is indistinguishable from being logged out

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/App.tsx:105
- 优先级：LOW
- 详细判断理由：审阅在此处确认“A failed session check is indistinguishable from being logged out”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：track a third bootstrap state for check failure with a retry button, distinct from a definitive 401

### A190. README run/config documentation is stale against the actual entrypoints

- 来源：bundle_mc_api_app
- 位置：src/mail_core/README.md:15
- 优先级：LOW
- 详细判断理由：审阅在此处确认“README run/config documentation is stale against the actual entrypoints”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：regenerate the tables from the argparse/env definitions and note the initial-password file lifecycle

### A191. LoginRateLimiter's key dict grows unboundedly for the process lifetime

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/security/ratelimit.py:29
- 优先级：LOW
- 详细判断理由：审阅在此处确认“LoginRateLimiter's key dict grows unboundedly for the process lifetime”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：return the deque without re-inserting when empty, and insert only in record_failure

### A192. fail_job leaves locked_by/locked_at set on terminally FAILED jobs

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/jobs.py:192
- 优先级：LOW
- 详细判断理由：审阅在此处确认“fail_job leaves locked_by/locked_at set on terminally FAILED jobs”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：clear locked_by/locked_at in the FAILED branch as well

### A193. （预存）Checkout persists the GITHUB_TOKEN in the workspace by default

- 来源：bundle_root_ci
- 位置：.github/workflows/ci.yml:119
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）Checkout persists the GITHUB_TOKEN in the workspace by default”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：set `persist-credentials: false` on all checkouts (no job pushes).

### A194. （预存）Scheduled drills have no concurrency guard

- 来源：bundle_root_ci
- 位置：.github/workflows/scheduled.yml:3
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）Scheduled drills have no concurrency guard”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add `concurrency: { group: scheduled-drills, cancel-in-progress: false }`.

### A195. Password file creation is a non-atomic read-then-write race

- 来源：bundle_desktop_scripts
- 位置：src/desktop/postgresManager.js:109
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Password file creation is a non-atomic read-then-write race”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：write with flag 'wx' and re-read on EEXIST so all callers converge on the first writer's value

### A196. pymap fallback exposes the IMAP password via process substitution argv

- 来源：bundle_desktop_scripts
- 位置：scripts/start-mail-core-imap.sh:38
- 优先级：LOW
- 详细判断理由：审阅在此处确认“pymap fallback exposes the IMAP password via process substitution argv”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：write the passfile to a 0600 temp file (with trap cleanup) and pass its path instead

### A197. （预存） Graph retry claim misplaces and mischaracterizes the backoff

- 来源：bundle_docs_live
- 位置：docs/blueprint/architecture.md:36
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存） Graph retry claim misplaces and mischaracterizes the backoff”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：describe the retry as living in the shared OAuth/HTTP transport with linear backoff, or implement/document the transport wrapper that actually retries Graph data calls.

### A198. （预存）fetchAccounts loops forever if the server keeps returning non-empty pages with has_more=true

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/queries.ts:153
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）fetchAccounts loops forever if the server keeps returning non-empty pages with has_more=true”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：cap iterations (e.g. 10_000 pages), verify offset progresses, and stop when accumulated length reaches res.total.

### A199. （预存）extractMessageIds can emit two different ids for one message

- 来源：bundle_frontend_state
- 位置：src/frontend/src/hooks/useMailCoreRealtime.ts:26
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）extractMessageIds can emit two different ids for one message”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：prefer message_id, fall back to id, and dedupe against message_ids.

### A200. （预存）parseSseChunk dispatches named events that carry no data, contrary to the SSE spec

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/sseStream.ts:35
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）parseSseChunk dispatches named events that carry no data, contrary to the SSE spec”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：dispatch only when dataBuffer is non-empty, regardless of event name.

### A201. Folder-tree duplicate-name disambiguation is O(n²) and folder React keys can collide （预存）

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/Sidebar.tsx:212
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Folder-tree duplicate-name disambiguation is O(n²) and folder React keys can collide （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：precompute label/suffix maps once per folders array with useMemo and include remote_id in the key before the name fallback

### A202. Advanced OAuth token_uri accepts any string, including http:// or non-URL values, with no UI validation

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/settings_account_form.tsx:341
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Advanced OAuth token_uri accepts any string, including http:// or non-URL values, with no UI validation”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：when non-empty, require `new URL(value)` to parse with protocol `https:` (allow http only for loopback) before submit and show the error in the form status

### A203. Detail-load failure renders the raw backend error message to the user

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/MessageReader.tsx:197
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Detail-load failure renders the raw backend error message to the user”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：use errorMessage with a Chinese fallback and log the raw error via diagnostics like ErrorBoundary does

### A204. Storage package exports omit models defined in its own models module

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/storage/__init__.py:3
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Storage package exports omit models defined in its own models module”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：export all ORM models from the package or none (and fix callers to one canonical path)

### A205. Corrupt blob digest on an attachment escapes as an unhandled 500

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/mail.py:544
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Corrupt blob digest on an attachment escapes as an unhandled 500”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：catch `InvalidBlobDigest` in the route (or translate it to `AttachmentAccessError` in the application layer) and return 404/410

### A206. rewrap limit always slices the same first N sorted paths, so limited runs never progress

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/blobs/rotate.py:128
- 优先级：LOW
- 详细判断理由：审阅在此处确认“rewrap limit always slices the same first N sorted paths, so limited runs never progress”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：filter to files whose on-disk version != target before applying limit

### A207. JSON credential without a password field falls back to using the entire JSON string as the password （预存）

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/factory.py:122
- 优先级：LOW
- 详细判断理由：审阅在此处确认“JSON credential without a password field falls back to using the entire JSON string as the password （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：raise a clear 'credential JSON missing password' error when neither field is present in a parsed dict secret

### A208. DeltaApplyResult.upserted counts unchanged rows as upserted

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/delta.py:174
- 优先级：LOW
- 详细判断理由：审阅在此处确认“DeltaApplyResult.upserted counts unchanged rows as upserted”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：count only outcomes with changed=True and report the page size separately if needed

### A209. （预存）cancel-in-progress also cancels main-branch gate runs

- 来源：bundle_root_ci
- 位置：.github/workflows/ci.yml:14
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）cancel-in-progress also cancels main-branch gate runs”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：set `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`.

### A210. （预存）navigationReset omits listFilter, so a smart-view filter leaks into account/folder views

- 来源：bundle_frontend_state
- 位置：src/frontend/src/store/mailStore.ts:64
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）navigationReset omits listFilter, so a smart-view filter leaks into account/folder views”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：reset listFilter to 'all' inside navigationReset or assert/define the intended carry-over in the store tests.

### A211. Provider state initializer relies on optional-chain equality narrowing (see re-check below)

- 来源：bundle_frontend_ui, bundle_regression
- 位置：src/frontend/src/components/settings_account_form.tsx:24
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Provider state initializer relies on optional-chain equality narrowing (see re-check below)”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：make the narrowing explicit, e.g. compute `const initialProvider: 'imap'|'gmail'|'graph' = account?.provider === 'gmail' ? 'gmail' : account?.provider === 'graph' ? 'graph' : 'imap'` above the hook

### A212. --proxy-headers flag is a silent no-op on its own

- 来源：bundle_mc_api_app
- 位置：src/mail_core/__main__.py:47
- 优先级：LOW
- 详细判断理由：审阅在此处确认“--proxy-headers flag is a silent no-op on its own”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：wire the flag to the same allow-ips mechanism before importing the app, and warn when proxy headers are requested without trusted hosts

### A213. Queue-full hint drops the oldest queued event and mislabels which event was dropped

- 来源：bundle_mc_api_app
- 位置：src/mail_core/realtime/dispatcher.py:75
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Queue-full hint drops the oldest queued event and mislabels which event was dropped”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：report the evicted event's id in the hint (capture it from `get_nowait()`), since that is the event the client will never see

### A214. Keyset list attributes multi-location messages to the lexicographically smallest folder UUID

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/queries.py:196
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Keyset list attributes multi-location messages to the lexicographically smallest folder UUID”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：prefer the folder(s) actually queried (pass the scope folder in) and only fall back to a deterministic location when unscoped

### A215. Same-state "transitions" are always allowed, including out of the terminal state

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/domain/archive.py:41
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Same-state "transitions" are always allowed, including out of the terminal state”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：only allow same-state for explicitly idempotent states, or return whether a transition actually occurred so callers can assert it

### A216. Domain enums have drifted from the values the code actually stores

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/domain/enums.py:25
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Domain enums have drifted from the values the code actually stores”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：extend the enums to cover stored values (or delete the unused members) and route status writes through them

### A217. Malformed backup key config raises raw ValueError/JSON errors instead of BackupCryptoError

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/backup/crypto.py:48
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Malformed backup key config raises raw ValueError/JSON errors instead of BackupCryptoError”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：wrap parsing in try/except and re-raise BackupCryptoError/BlobCryptoError with the offending variable name

### A218. Persisted bcrypt hash file is written with default (umask) permissions

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/security/auth.py:230
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Persisted bcrypt hash file is written with default (umask) permissions”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：write via os.open with 0o600 (and chmod existing files), as backup/crypto.py does for key material

### A219. 0013 downgrade re-imposes NOT NULL on login_password_hash with no NULL guard

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/db/alembic/versions/20261021_0013_auth_credentials_session_epoch.py:31
- 优先级：LOW
- 详细判断理由：审阅在此处确认“0013 downgrade re-imposes NOT NULL on login_password_hash with no NULL guard”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：check for NULL hashes first and raise a clear RuntimeError like 0017 does

### A220. BlobStore.put swallows every exception from existing-blob verification

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/blobs/store.py:90
- 优先级：LOW
- 详细判断理由：审阅在此处确认“BlobStore.put swallows every exception from existing-blob verification”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：only swallow BlobCryptoError hash/auth mismatch; propagate BlobCryptoError for unknown key versions and OSError

### A221. merge_credentials can never clear a credential field

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/accounts/connection.py:25
- 优先级：LOW
- 详细判断理由：审阅在此处确认“merge_credentials can never clear a credential field”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：treat an explicit empty string for optional fields (client_secret) as deletion, or add an explicit clear-list parameter

### A222. \_connect mutates the global imaplib.Commands table and uses a private API （预存）

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/imap.py:361
- 优先级：LOW
- 详细判断理由：审阅在此处确认“\_connect mutates the global imaplib.Commands table and uses a private API （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：register the ID command once at module import under a lock, and wrap the private call in a version-tolerant helper

### A223. MemoryProvider.flag_message rebuilds meta dropping threading fields

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/stub_memory.py:71
- 优先级：LOW
- 详细判断理由：审阅在此处确认“MemoryProvider.flag_message rebuilds meta dropping threading fields”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：copy all fields from the original meta (dataclasses.replace) instead of enumerating a subset

### A224. Search ILIKE patterns do not escape % and _ in the user query

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/search/index.py:43
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Search ILIKE patterns do not escape % and _ in the user query”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：escape backslash, % and _ in the query for the ILIKE branches with an explicit ESCAPE clause

### A225. GmailNotConfiguredError documentation is stale

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/gmail.py:36
- 优先级：LOW
- 详细判断理由：审阅在此处确认“GmailNotConfiguredError documentation is stale”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：update the docstring (and the graph twin) to describe the actual misconfiguration condition

### A226. （预存）Drill artifacts uploaded unconditionally, including on failure/cancellation

- 来源：bundle_root_ci
- 位置：.github/workflows/scheduled.yml:57
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）Drill artifacts uploaded unconditionally, including on failure/cancellation”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：upload only on failure like ci.yml:162, or restrict paths to logs/summaries excluding backup payloads.

### A227. （预存）Cache helpers ignore a bare `{items:[…]}` page object, so plain (non-infinite) PageOut cache entries are invisible to optimistic updates

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/queries.ts:179
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）Cache helpers ignore a bare `{items:[…]}` page object, so plain (non-infinite) PageOut cache entries are invisible to optimistic updates”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：handle the `{items}` shape at the top level in both helpers.

### A228. Instance token is accepted as a CLI argument

- 来源：bundle_mc_api_app
- 位置：src/mail_core/__main__.py:43
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Instance token is accepted as a CLI argument”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：drop the CLI flag (keep `KKMAIL_INSTANCE_TOKEN` env only) or read the value from a file path argument

### A229. Malformed job payloads are misattributed as account sync failures

- 来源：bundle_mc_api_app
- 位置：src/mail_core/worker/handlers.py:151
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Malformed job payloads are misattributed as account sync failures”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：validate required payload fields up front and fail such jobs as `invalid_payload` without touching account sync status

### A230. MessageDetail construction is duplicated wholesale between detail and sync-body

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/mail.py:439
- 优先级：LOW
- 详细判断理由：审阅在此处确认“MessageDetail construction is duplicated wholesale between detail and sync-body”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：extract one `_detail_out(session, message_id)` helper used by both routes

### A231. Composite/save_json_secret TypeError fallback can mask real errors and escape the caller's transaction

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/accounts/credentials.py:234
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Composite/save_json_secret TypeError fallback can mask real errors and escape the caller's transaction”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：only use the no-session call for stores whose signature lacks `session` (inspect once at construction), never as an exception fallback

### A232. Passwords longer than bcrypt's 72-byte limit are silently truncated

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/security/auth.py:390
- 优先级：LOW
- 详细判断理由：bcrypt 72-byte 截断会让超过上限的新密码产生歧义；新增 UTF-8 字节长度校验可防止新账号设置不可区分的超长密码，同时保留既有 bcrypt 验证算法与存量哈希。不得引入预哈希。
- 修复说明：仅拒绝 UTF-8 编码后超过 72 字节的新密码；保持现有 `bcrypt.checkpw` 与所有已存储哈希格式不变，不做 SHA-256 pre-hash。

### A233. Alembic env calls fileConfig with default disable_existing_loggers=True

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/db/alembic/env.py:24
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Alembic env calls fileConfig with default disable_existing_loggers=True”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：pass `disable_existing_loggers=False`

### A234. Rewrap uses a fixed per-file temp name, so concurrent rotations collide

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/blobs/rotate.py:82
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Rewrap uses a fixed per-file temp name, so concurrent rotations collide”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：use a unique temp name in the same directory (uuid suffix) and unlink leftovers

### A235. Restore loads each blob fully into memory and writes it non-atomically

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/backup/package.py:779
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Restore loads each blob fully into memory and writes it non-atomically”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：stream-copy in chunks to a temp file, fsync, then rename

### A236. Gmail/Graph accounts without credential_ref get a provider that fails every call at runtime

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/factory.py:143
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Gmail/Graph accounts without credential_ref get a provider that fails every call at runtime”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：raise a configuration/auth error at build time when credential_ref is empty for gmail/graph providers

### A237. Fetch-timeout lookup failures are silently swallowed to a 30s default

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/factory.py:93
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Fetch-timeout lookup failures are silently swallowed to a 30s default”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：log the exception at warning level with the account context before falling back to the default

### A238. list_folders raises KeyError on a label payload without 'id'

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/gmail.py:193
- 优先级：LOW
- 详细判断理由：审阅在此处确认“list_folders raises KeyError on a label payload without 'id'”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：skip labels without an id (with a debug log) instead of failing the whole listing

### A239. History stub meta claims to be a complete snapshot (supplied_fields=None)

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/parsing/gmail_history.py:48
- 优先级：LOW
- 详细判断理由：审阅在此处确认“History stub meta claims to be a complete snapshot (supplied_fields=None)”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：set supplied_fields on stub metas to only the fields actually present, mirroring gmail.py's \_meta_from_gmail_message

### A240. （预存）FORBID_ATTR does not include `ping`, so sanitized links can beacon the reader on click

- 来源：bundle_frontend_state
- 位置：src/frontend/src/lib/mailBody.ts:25
- 优先级：LOW
- 详细判断理由：审阅在此处确认“（预存）FORBID_ATTR does not include `ping`, so sanitized links can beacon the reader on click”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add 'ping' (and 'background') to FORBID_ATTR.

### A241. ProxyHeaders middleware silently absent when uvicorn's module import fails

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/app.py:77
- 优先级：LOW
- 详细判断理由：审阅在此处确认“ProxyHeaders middleware silently absent when uvicorn's module import fails”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：log an error at startup when trusted hosts are configured but the middleware cannot be installed

### A242. Plaintext initial password persists until the user happens to change it

- 来源：bundle_mc_api_app
- 位置：src/mail_core/runtime/bootstrap.py:81
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Plaintext initial password persists until the user happens to change it”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：document the file and its lifecycle in the README, and consider deleting it after first successful login instead of first password change

### A243. LISTEN connection has no connect timeout and the DSN shim only handles two driver prefixes

- 来源：bundle_mc_api_app
- 位置：src/mail_core/realtime/listener.py:79
- 优先级：LOW
- 详细判断理由：审阅在此处确认“LISTEN connection has no connect timeout and the DSN shim only handles two driver prefixes”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：add `connect_timeout=5` and normalize/reject unsupported schemes with one clear startup error

### A244. Account email is not format-validated for non-network providers

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/accounts.py:82
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Account email is not format-validated for non-network providers”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：validate a basic email shape in the route (or in `create_account_app`) for all providers

### A245. mark-all-read response echoes the request's account_id even for group/global scopes

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/mail.py:502
- 优先级：LOW
- 详细判断理由：审阅在此处确认“mark-all-read response echoes the request's account_id even for group/global scopes”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：return the effective scope (scope type + id) actually used by `mark_all_messages_read`

### A246. Successful remote ops keep their stale last_error

- 来源：bundle_mc_api_app, bundle_regression
- 位置：src/mail_core/mail/application/remote_ops.py:174
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Successful remote ops keep their stale last_error”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：clear `last_error` when transitioning to DONE (and to IN_PROGRESS on a fresh attempt)

### A247. Unknown stored archive state raises bare ValueError, not IllegalArchiveTransition

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/domain/archive.py:56
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Unknown stored archive state raises bare ValueError, not IllegalArchiveTransition”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：wrap the conversion and raise IllegalArchiveTransition (or a dedicated corrupt-state error) naming the offending value

### A248. rename_group_app materializes every member account id just to count them

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/accounts.py:352
- 优先级：LOW
- 详细判断理由：审阅在此处确认“rename_group_app materializes every member account id just to count them”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：use `func.count()` for the rename count and a plain id→group select for the DTO map

### A249. DB-backed API/SSE tests skip silently outside the gated test script

- 来源：bundle_mc_api_app
- 位置：tests/mail_core/test_sse_outbox.py:19
- 优先级：LOW
- 详细判断理由：审阅在此处确认“DB-backed API/SSE tests skip silently outside the gated test script”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：make the default in CI the REQUIRE_DB behavior, or emit an explicit warning summary of skipped DB tests in the gate

### A250. Key loaders use base64.b64decode without validate=True

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/blobs/crypto.py:56
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Key loaders use base64.b64decode without validate=True”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：`base64.b64decode(raw, validate=True)` and raise the domain error on binascii.Error

### A251. safe_provider_summary returns full redacted text for string input despite its "bodies are dropped" contract

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/security/redact.py:82
- 优先级：LOW
- 详细判断理由：审阅在此处确认“safe_provider_summary returns full redacted text for string input despite its "bodies are dropped" contract”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：for string input return only a controlled prefix/type summary like the exception branch, or truncate to a fixed safe vocabulary

### A252. iter_plaintext yields plaintext before the content-digest check runs

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/blobs/store.py:133
- 优先级：LOW
- 详细判断理由：审阅在此处确认“iter_plaintext yields plaintext before the content-digest check runs”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：document that streaming callers must treat a trailing BlobCryptoError as response failure, or buffer/verify before first byte for non-idempotent consumers

### A253. Google callback exchange never re-checks flow expiry after the network calls

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/accounts/google_oauth.py:23
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Google callback exchange never re-checks flow expiry after the network calls”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：re-check expiry immediately before setting `flow["status"] = "authorized"`

### A254. Failed plain-package creation leaves a partial postgres.dump in the output directory

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/backup/package.py:318
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Failed plain-package creation leaves a partial postgres.dump in the output directory”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：build plain packages in a staging dir and rename on success, like run_backup does

### A255. session_max_age crashes with a bare ValueError on malformed env

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/security/auth.py:74
- 优先级：LOW
- 详细判断理由：审阅在此处确认“session_max_age crashes with a bare ValueError on malformed env”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：parse once in validate_auth_config and raise AuthConfigError naming the variable

### A256. Token endpoint error_description is interpolated into exception messages （预存）

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/oauth.py:142
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Token endpoint error_description is interpolated into exception messages （预存）”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：truncate and sanitize endpoint error text (strip control chars, cap length) before embedding it in OAuthError

### A257. PermanentAuthError classification relies on fragile server-message substrings

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/imap.py:367
- 优先级：LOW
- 详细判断理由：审阅在此处确认“PermanentAuthError classification relies on fragile server-message substrings”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：classify permanence on protocol response codes where available and treat unknown auth failures as retryable with backoff, escalating only after repeated failures

### A258. assert_fencing compares lease_expires_at to an aware now without tz normalization

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/leases.py:135
- 优先级：LOW
- 详细判断理由：审阅在此处确认“assert_fencing compares lease_expires_at to an aware now without tz normalization”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：normalize naive expiries to UTC in assert_fencing (and heartbeat/release) exactly as acquire_lease does

### A259. MemoryProvider change_log grows without bound on a production-reachable path

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/stub_memory.py:29
- 优先级：LOW
- 详细判断理由：审阅在此处确认“MemoryProvider change_log grows without bound on a production-reachable path”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：prune change_log entries at or below the minimum outstanding consumer modseq, or cap the log with a documented rebuild fallback

### A260. Client-supplied X-Request-ID is trusted, unbounded and reflected

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/app.py:109
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Client-supplied X-Request-ID is trusted, unbounded and reflected”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：accept only a bounded token (`^[A-Za-z0-9._-]{1,64}$`), otherwise generate `req_<hex>` as today

### A261. A bad Bearer header hard-fails even when a valid session cookie is present

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/deps.py:38
- 优先级：LOW
- 详细判断理由：审阅在此处确认“A bad Bearer header hard-fails even when a valid session cookie is present”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：fall through to session auth when the Bearer token doesn't match (still 401 if neither works), or document the precedence in the API contract

### A262. Login rate limiting keys on the direct peer IP only

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/auth_routes.py:63
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Login rate limiting keys on the direct peer IP only”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：document the proxy assumption next to the limiter and, when `MAIL_CORE_FORWARDED_ALLOW_IPS` is set, key on the forwarded client IP

### A263. Slow-writer race in \_read_or_create can return an empty secret

- 来源：bundle_mc_api_app
- 位置：src/mail_core/runtime/bootstrap.py:40
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Slow-writer race in \_read_or_create can return an empty secret”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：wait until the file is non-empty with a bounded deadline and raise a clear bootstrap error on timeout

### A264. Worker crashes on a malformed numeric env var

- 来源：bundle_mc_api_app
- 位置：src/mail_core/worker/main.py:173
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Worker crashes on a malformed numeric env var”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：parse with a helper that falls back to the default and logs the offending value

### A265. Sync result dicts are logged wholesale at INFO

- 来源：bundle_mc_api_app
- 位置：src/mail_core/worker/handlers.py:138
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Sync result dicts are logged wholesale at INFO”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：log a whitelisted summary (status, counts, duration) instead of the raw result dict

### A266. SSE connection cap is parsed at import time and crashes the whole API on a bad value

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/sse.py:32
- 优先级：LOW
- 详细判断理由：审阅在此处确认“SSE connection cap is parsed at import time and crashes the whole API on a bad value”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：parse lazily with a fallback-and-warn helper, as with other numeric env settings

### A267. Settings patch payload is unbounded in key count and value size

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/accounts.py:169
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Settings patch payload is unbounded in key count and value size”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：bound the dict (e.g. ≤ 100 keys, keys ≤ 128, values ≤ 4096 chars) at the schema layer

### A268. Global/group inbox stats read result columns by fragile positional indices

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/queries.py:404
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Global/group inbox stats read result columns by fragile positional indices”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：label every selected column and access by key, and share one implementation between the global and group variants

### A269. Coalesce path is not account-scoped and takes no row lock

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/remote_ops.py:17
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Coalesce path is not account-scoped and takes no row lock”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：scope the lookup by account_id, lock the row on the coalesce path, and verify entity/op ownership before mutating

### A270. AccountDTO.status conflates "account disabled" with "sync disabled"

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/accounts.py:125
- 优先级：LOW
- 详细判断理由：审阅在此处确认“AccountDTO.status conflates "account disabled" with "sync disabled"”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：carry a real account status field, or rename the DTO field to reflect that it is sync state

### A271. 0003 downgrade drops message_search with CASCADE

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/db/alembic/versions/20261021_0003_message_fts.py:43
- 优先级：LOW
- 详细判断理由：审阅在此处确认“0003 downgrade drops message_search with CASCADE”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：drop without CASCADE and let dependents block the downgrade loudly

### A272. token_uri allowlist is only enforced when a token_uri is present

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/accounts/connection.py:87
- 优先级：LOW
- 详细判断理由：审阅在此处确认“token_uri allowlist is only enforced when a token_uri is present”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：require token_uri for gmail/graph at validation time or assert the provider layer always substitutes the allowlisted default (and test that)

### A273. \_validate_public_origin accepts HTTPS loopback/private origins, contradicting its own operator notice

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/accounts/oauth_flow.py:126
- 优先级：LOW
- 详细判断理由：审阅在此处确认“\_validate_public_origin accepts HTTPS loopback/private origins, contradicting its own operator notice”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：reject loopback/link-local hostnames unless MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN is set, regardless of scheme

### A274. Concurrent run_backup calls to the same destination race the directory swap

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/backup/package.py:651
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Concurrent run_backup calls to the same destination race the directory swap”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：hold an flock on a sibling lockfile for the whole create+verify+swap

### A275. fetch_metadata_page silently drops items the delta parser classifies as flag-only

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/graph.py:154
- 优先级：LOW
- 详细判断理由：审阅在此处确认“fetch_metadata_page silently drops items the delta parser classifies as flag-only”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：give the list path its own parser that always materializes a meta per item instead of reusing delta classification

### A276. normalize_message_id wraps arbitrary tokens in angle brackets

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/threading/rules.py:47
- 优先级：LOW
- 详细判断理由：审阅在此处确认“normalize_message_id wraps arbitrary tokens in angle brackets”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：return None for values that contain neither an '@' token nor a bracketed id, mirroring extract_message_ids strictness

### A277. search_messages does not clamp limit

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/search/index.py:84
- 优先级：LOW
- 详细判断理由：审阅在此处确认“search_messages does not clamp limit”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：clamp limit into a sane range (e.g. 1..200) in search_messages/count callers' shared helper

### A278. SPA fallback prefix check is over-broad and error-swallowing

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/app.py:203
- 优先级：LOW
- 详细判断理由：审阅在此处确认“SPA fallback prefix check is over-broad and error-swallowing”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：compare the first path segment exactly, and log unexpected resolve errors at debug instead of swallowing all exceptions

### A279. pg_notify failures are visible only at debug level

- 来源：bundle_mc_api_app
- 位置：src/mail_core/realtime/notify.py:23
- 优先级：LOW
- 详细判断理由：审阅在此处确认“pg_notify failures are visible only at debug level”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：rate-limited warning (first failure + hourly summary) while keeping per-call failures non-fatal

### A280. Negative or malformed replay cursors are handled inconsistently

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/sse.py:161
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Negative or malformed replay cursors are handled inconsistently”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：treat `cursor < 0` as malformed in the same path as the header parse failure

### A281. Sidebar layout payload lists are unbounded

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/accounts.py:130
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Sidebar layout payload lists are unbounded”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：cap list lengths to a plausible ceiling (accounts + groups count) at the schema layer

### A282. Search accepts whitespace-only queries

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/mail.py:274
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Search accepts whitespace-only queries”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：strip and require a non-empty query in the route

### A283. Attachment media type is taken verbatim from parsed MIME data

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/mail.py:556
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Attachment media type is taken verbatim from parsed MIME data”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：validate against a token/token media-type pattern and fall back to application/octet-stream

### A284. Worker-loop test relies on a fixed sleep

- 来源：bundle_mc_api_app
- 位置：tests/mail_core/test_worker_loop.py:23
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Worker-loop test relies on a fixed sleep”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：poll for the expected condition with a deadline instead of sleeping a fixed duration

### A285. Global engine replacement is not thread-safe

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/db/session.py:39
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Global engine replacement is not thread-safe”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：guard engine creation/swap with a threading.Lock

### A286. Login password has no maximum length

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/auth_routes.py:27
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Login password has no maximum length”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：cap password fields at a sane maximum (e.g. 1024 chars) on LoginIn and PasswordChangeIn

### A287. get_oauth_flow_status reads the flow without the credential_edit lock

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/accounts/oauth_flow.py:448
- 优先级：LOW
- 详细判断理由：审阅在此处确认“get_oauth_flow_status reads the flow without the credential_edit lock”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：read under credential_edit (read-only use) for status/cancel, as consume paths do

### A288. TRACE is classified as a CSRF-safe method

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/deps.py:19
- 优先级：LOW
- 详细判断理由：审阅在此处确认“TRACE is classified as a CSRF-safe method”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：drop TRACE from `_SAFE_METHODS`

### A289. Restore verifies the package, then re-reads it from the mutable directory (verify/restore TOCTOU)

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/backup/package.py:723
- 优先级：LOW
- 详细判断理由：审阅在此处确认“Restore verifies the package, then re-reads it from the mutable directory (verify/restore TOCTOU)”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：copy/hash the kkbak into the private work dir during verify and restore only from that copy

### A290. Gmail 'historyid' error mapping (round-2 addendum residual) | \_raise_mapped still maps any error whose body merely contains 'historyid' to CursorInvalidError regardless of endpoint or status: 'if "historyid" in text or (status in (404, 410) and …)' at :71-75; the :70 comment gates only the bare-404 branch, not the historyid substring branch

- 来源：bundle_regression
- 位置：src/mail_core/providers/gmail.py:71
- 优先级：MEDIUM
- 详细判断理由：审阅在此处确认“Gmail 'historyid' error mapping (round-2 addendum residual) | \_raise_mapped still maps any error whose body merely contains 'historyid' to CursorInvalidError regardless of endpoint or status: 'if "historyid" in text or (status in (404, 410) and …)' at :71-75; the :70 comment gates only the bare-404 branch, not the historyid substring branch”仍可触发；会造成错误行为、失败不可见或契约偏差，修复收益明确且范围局部，采纳。
- 修复说明：仅将明确的 history cursor 失效响应映射为 CursorInvalidError；不得仅凭任意响应正文含 historyid 子串触发游标重建，并补充状态碼与 endpoint 组合覆蓋。

### A291. 账号邮箱大小写归一与唯一索引迁移

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/storage/models.py:92
- 优先级：LOW
- 详细判断理由：同一邮箱大小写不同可形成重复账号；数据库索引迁移可能遇到现存冲突，必须先定迁移策略。 用户已选择选项 A，纳入采纳项。
- 修复说明：新账号写入前统一邮箱小写，并添加 lower(email) 唯一索引。迁移前审计大小写重复并创建可恢复备份；若发现冲突，先明确逐账号处理方案，不自动合并。

### A292. 长邮件列表采用虚拟滚动还是限制挂载数量

- 来源：bundle_cross_validation, bundle_frontend_ui
- 位置：src/frontend/src/components/MessageList.tsx:582
- 优先级：HIGH
- 详细判断理由：无限加载让 DOM 与每次列表更新成本持续增长；虚拟滚动改动较大并可能影响键盘/滚动行为，需选择交互与依赖方案。 用户已选择选项 A，纳入采纳项。
- 修复说明：为邮件行加入窗口化虚拟滚动；将 selectedIds 查找改为 Set，同时保持无限加载、键盘选择、滚动定位与当前 scope 行为。

### A293. 按需正文同步的 HTTP 时序与失败反馈契约

- 来源：bundle_cross_validation, bundle_mc_api_app
- 位置：src/mail_core/api/mail.py:412; src/mail_core/api/mail.py:419
- 优先级：HIGH
- 详细判断理由：当前前端把 sync-body 响应作为 `MailCoreMessageDetail` 更新阅读器。用户已选择异步方案；采纳范围必须覆盖 OpenAPI、API client、MessageReader 状态处理和相关契约测试，禁止只改后端返回 202。
- 修复说明：将 sync-body 改为仅排队并返回 202；同步更新 OpenAPI 与 `postMailCoreSyncMessageBody` 返回类型，调整 MessageReader 通过状态/事件呈现处理中、完成和失败，并更新接口及阅读器测试；移除请求内归档执行，避免重复工作。

### A294. 清理历史公开的凭据、个人数据与机器路径

- 来源：bundle_cross_validation, bundle_docs_archive, bundle_docs_reviews, bundle_privacy_history, bundle_regression, bundle_regression_addendum, review_intensive
- 位置：docs/reviews/review_20261021_040521/bundle_v1_security.md:21; docs/reviews/review_20261022_052842/bundle_v1_security.md:10; docs/reviews/review_20261022_052842/bundle_cross_validation.md:17; docs/reviews/review_20261022_052842/bundle_v1_security.md:12; docs/archive/pending/p027_account_folder_sync_failure_and_unknown_unread_badge.md:11; docs/reviews/review_20261022_052842/review_intensive.md:18; docs/reviews/review_20261022_052842/bundle_v6_robustness.md:11; docs/reviews/review_20261022_052842/bundle_cross_validation.md:47; docs/reviews/review_20261021_040521/summary_verification_report.md:38; docs/archive/pending/p028_mail_list_cache_prefix_folder_collision.md:4; docs/reviews/review_20261021_040521/bundle_cross_validation.md:21; web_outlook_app.py:27; docs/reviews/review_20261022_052842/bundle_v1_security.md:11; docs/archive/tasks/t055_microsoft_oauth_callback/review_code.md:6; docs/archive/tasks/t053_provider_account_forms/review_test.md:145; docs/archive/pending/p034_account_sync_failure_self_healing_and_sidebar_status_discrepancy.md:4; docs/archive/tasks/t027_account_group_ordering/source_notes.md:6; docs/reviews/review_20261022_052842/bundle_v1_security.md:19; docs/reviews/review_20261022_052842/adoption_decision.md:452; docs/reviews/review_20261021_040521/bundle_v1_security.md:46; docs/archive/pending/p031_repaired_mime_parse_error_blocks_body_and_fetch_error_conflation.md:6; docs/archive/tasks/t006_dark_reader_theme/review_code.md:6; docs/reviews/review_20261021_034329/\_meta/\_meta.json:4; docs/reviews/review_20261021_040521/\_meta/\_meta.json:4; docs/reviews/review_20261021_064335/review_da57df7_findings_and_decisions.md:3; docs/reviews/review_20261021_040521/bundle_v8_docs.md:12; docs/reviews/review_20261021_034329/\_meta/rubric.md:35; docs/archive/pending/p031_repaired_mime_parse_error_blocks_body_and_fetch_error_conflation.md:11; docs/archive/tasks/t049_sync_retry_double_enqueue/task.md:33; docs/archive/pending/p035_empty_archived_mail_body_placeholder.md:3; docs/reviews/（多个历史审阅包；聚合项）
- 优先级：CRITICAL
- 详细判断理由：用户最初选择原 D1-B。已完成当前副本清理、全 refs/tags 备份与恢复核验，以及本地所有 refs/tags 和远端原有 `main`/120 个 tag 的历史重写。后续用户确认历史 `EMAIL` 对应账户不属于本人，并明确将凭据撤销/轮换及 GitHub PR 引用/缓存清理请求列为不采纳，见 R91/R92。远端 `refs/pull/1/head` 未改写，仍可达旧历史；账户凭据有效性未知。
- 修复说明：从当前树移除敏感值、个人标识和机器路径；备份并恢复核验全部本地 refs/tags；重写本地历史，并以 lease 更新远端原有分支/tag refs，不发布本地领先提交。第三方账户凭据撤销及 GitHub PR 引用/缓存清理按 R91/R92 拒绝处理。

### A295. 保留 LAN HTTP 部署并明确 Cookie 安全边界

- 来源：bundle_root_ci
- 位置：docker-compose.mail-core.yml:63；docs/guides/deployment.md:19,33
- 优先级：MEDIUM
- 详细判断理由：用户选择原 D2-A。现有 Compose 与部署指南支持 loopback/LAN HTTP；Compose 无法按 HOST_BIND 条件校验 COOKIE_SECURE。保留现有部署行为，并在文档明确 HTTP 会话 Cookie 风险及敏感远程访问要求。
- 修复说明：保留 loopback/LAN HTTP 默认行为；更新部署文档，说明 HTTP 会话 Cookie 暴露风险，并要求敏感远程访问使用 TLS 且设置 `MAIL_CORE_COOKIE_SECURE=1`。

### A296. 通过跨进程撤销通知关闭失效会话的 SSE 流

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/sse.py:151
- 优先级：MEDIUM
- 详细判断理由：用户选择原 D3-B。auth_and_session AC-004 要求登出或改密后立即撤销旧会话；SSE 若每 15 秒轮询数据库会增加持续负载。跨 API 进程撤销通知可保留流级撤销语义，并避免固定频率查询数据库。
- 修复说明：登出或改密时发布可跨 API 进程传递的会话撤销信号并关闭对应 SSE 流；增加有界数据库复核作为通知丢失时的兜底，并验证连接上限和多进程行为。

## 不采纳项

### R1. Verification headline count still contradicts its own table

- 来源：bundle_cross_validation, bundle_docs_reviews, bundle_regression, bundle_regression_addendum
- 位置：docs/reviews/review_20261021_040521/summary_verification_report.md:9
- 优先级：HIGH
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R2. Machine bundle totals still contradict the pack's own meta

- 来源：bundle_cross_validation, bundle_regression, bundle_regression_addendum
- 位置：docs/reviews/review_20261021_011116/bundle_zz_findings_machine.md:5
- 优先级：HIGH
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R3. Scope stats still false and byte-identical to another review's scope

- 来源：bundle_cross_validation, bundle_regression, bundle_regression_addendum
- 位置：docs/reviews/review_20261021_034329/bundle.json:543
- 优先级：HIGH
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R4. Timed-out pack still presented as complete

- 来源：bundle_cross_validation, bundle_docs_reviews, bundle_regression, bundle_regression_addendum
- 位置：docs/reviews/review_20261021_040521/\_meta/\_meta.json:19
- 优先级：HIGH
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R5. Baseline conflation and 'all real' verdict still standing

- 来源：bundle_cross_validation, bundle_regression, bundle_regression_addendum
- 位置：docs/reviews/review_20261021_040521/summary_verification_report.md:8
- 优先级：HIGH
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R6. Banner falsely claims all defects thoroughly fixed and closed as of da57df7

- 来源：bundle_cross_validation, bundle_docs_reviews
- 位置：docs/reviews/review_20261021_040521/summary_verification_report.md:3
- 优先级：HIGH
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R7. Unauthenticated /health leaks the desktop instance token

- 来源：bundle_cross_validation, bundle_mc_api_app
- 位置：src/mail_core/api/app.py:160
- 优先级：HIGH
- 详细判断理由：Cross-validation 证实该值是每次启动生成的 sidecar 身份 nonce，唯一消費者只用于本地 health 回显比对；它不认证 API，High 嚴重度被高估，按本次证偽结论不采纳。

### R8. Shared root causes still double/triple-counted in verified totals

- 来源：bundle_cross_validation, bundle_regression, bundle_regression_addendum
- 位置：docs/reviews/review_20261021_040521/summary_verification_report.md:22
- 优先级：HIGH
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R9. Two committed decision records directly contradict each other on the same credential with no supersession marker

- 来源：bundle_cross_validation, bundle_docs_reviews
- 位置：docs/reviews/review_20261022_052842/adoption_decision.md:441
- 优先级：HIGH
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R10. Whole 052842 pack presents stale findings as current with no status banner

- 来源：bundle_cross_validation, bundle_docs_reviews
- 位置：docs/reviews/review_20261022_052842/review_intensive.md:7
- 优先级：HIGH
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R11. Coalescing an IN_PROGRESS remote op resets it to PENDING under the in-flight push (lost update)

- 来源：bundle_cross_validation, bundle_mc_api_app
- 位置：src/mail_core/mail/application/remote_ops.py:35
- 优先级：HIGH
- 详细判断理由：Cross-validation 找到完成路径的 revision/status CAS：并发 coalesce 会使旧任务完成检查失败并保留后续 PENDING 状态；原报告所称靜默丟更新在该路径未复现，按证偽结论不采纳。

### R12. Archived doc asserts the repo has no CI, contradicting current repo and live blueprint （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/legacy_architecture/mail-core-architecture.md:707
- 优先级：MEDIUM
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R13. Aborted review session committed as a pack: 17 of 18 expected reports missing

- 来源：bundle_docs_reviews, bundle_regression
- 位置：docs/reviews/review_20261021_034329/\_meta/\_meta.json:27
- 优先级：MEDIUM
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R14. Archived (closed) pending notes still framed as live, urgent breakage with no closure banner （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/pending/p005_worker_unbound_local_account.md:3
- 优先级：MEDIUM
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R15. Archived changelog's [Unreleased] section asserts states that are now false and points at dead doc paths （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/CHANGELOG.md:37
- 优先级：MEDIUM
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R16. Verification table restates a working short-form recipe for the credential

- 来源：bundle_docs_reviews
- 位置：docs/reviews/review_20261021_040521/summary_verification_report.md:59
- 优先级：MEDIUM
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R17. Pending fix-refs are unresolvable, so closure cannot be verified from the archive （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/pending/p006_attachment_size_human_readable.md:8
- 优先级：MEDIUM
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R18. Unverified credential validity asserted as fact, contradicting the earlier pack

- 来源：bundle_docs_reviews
- 位置：docs/reviews/review_20261022_052842/review_intensive.md:11
- 优先级：MEDIUM
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R19. Done tasks' spec acceptance criteria left unchecked, so specs read as unmet （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/tasks/t027_account_group_ordering/spec.md:32
- 优先级：MEDIUM
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R20. Newest pack also has no status banner and its baseline no longer exists in the clone

- 来源：bundle_docs_reviews
- 位置：docs/reviews/review_20261022_071448/review_intensive.md:19
- 优先级：MEDIUM
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R21. Sole-authority claim contradicted by later decision packs

- 来源：bundle_docs_reviews
- 位置：docs/reviews/review_20261021_064335/review_da57df7_findings_and_decisions.md:20
- 优先级：MEDIUM
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R22. Right-click context menu omits the disabled send item required by spec AC-010

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/MessageList.tsx:671
- 优先级：MEDIUM
- 详细判断理由：产品范围明确排除发信。为满足过时 AC 增加禁用发信入口会繼续暗示该功能受支持，当前代碼符合产品边界，不采纳。

### R23. Broken intra-archive links (double `archive/` segment) （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/tasks/t027_account_group_ordering/spec.md:85
- 优先级：LOW
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R24. Link to a pending file at its pre-archive location （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/tasks/t037_legacy_migration_fidelity/task.md:32
- 优先级：LOW
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R25. Dedup failure inside the aggregate that claims to be deduped

- 来源：bundle_docs_reviews
- 位置：docs/reviews/review_20261022_052842/review_intensive.md:21
- 优先级：LOW
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R26. PostgresManager.\_child is dead state

- 来源：bundle_desktop_scripts
- 位置：src/desktop/postgresManager.js:91
- 优先级：LOW
- 详细判断理由：建议主要涉及命名、死代碼或低频性能优化；当前无可见行为故障，且清理收益不足以承擔額外改动面，暂不采纳。

### R27. Dead imports and dead code in the E2E runner

- 来源：bundle_desktop_scripts
- 位置：scripts/run_full_stack_e2e.py:7
- 优先级：LOW
- 详细判断理由：建议主要涉及命名、死代碼或低频性能优化；当前无可见行为故障，且清理收益不足以承擔額外改动面，暂不采纳。

### R28. Dead relative links inside the archived architecture doc （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/legacy_architecture/mail-core-architecture.md:172
- 优先级：LOW
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R29. Stale contract/source paths in archived architecture doc （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/legacy_architecture/mail-core-architecture.md:667
- 优先级：LOW
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R30. 21 archived tasks have no handoff.json, leaving an evidence gap a reader must reconstruct （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/tasks/t013_test_pg_runtime/task.md:57
- 优先级：LOW
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R31. （预存）canSendFrom is dead code for a product whose scope excludes sending

- 来源：bundle_frontend_state
- 位置：src/frontend/src/lib/accounts.ts:10
- 优先级：LOW
- 详细判断理由：建议主要涉及命名、死代碼或低频性能优化；当前无可见行为故障，且清理收益不足以承擔額外改动面，暂不采纳。

### R32. Stale 'current gap' claim about sidebar unread badges （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/legacy_architecture/mail-core-architecture.md:587
- 优先级：LOW
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R33. Evidence trail depends on un-archived .scratch artefacts and agent session residue （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/pending/p039_body_sync_retry_loop.md:7
- 优先级：LOW
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R34. （预存）No suite-wide timezone pin: hermeticity rests on per-test discipline while CI runners are UTC

- 来源：bundle_frontend_state
- 位置：src/frontend/src/lib/listDate.test.ts:8
- 优先级：LOW
- 详细判断理由：建议主要涉及命名、死代碼或低频性能优化；当前无可见行为故障，且清理收益不足以承擔額外改动面，暂不采纳。

### R35. Domain value objects are dead code

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/domain/models.py:30
- 优先级：LOW
- 详细判断理由：建议主要涉及命名、死代碼或低频性能优化；当前无可见行为故障，且清理收益不足以承擔額外改动面，暂不采纳。

### R36. Re-check (i) residual: banner added but body verdict still reads as a live BLOCK

- 来源：bundle_docs_reviews
- 位置：docs/reviews/review_20261021_011116/review_intensive.md:13
- 优先级：LOW
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R37. list_accounts runs redundant full-table count queries per call

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/accounts/service.py:89
- 优先级：LOW
- 详细判断理由：建议主要涉及命名、死代碼或低频性能优化；当前无可见行为故障，且清理收益不足以承擔額外改动面，暂不采纳。

### R38. recompute_folder_stats creates a stats row for a folder that may not exist

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/storage/folder_stats.py:15
- 优先级：LOW
- 详细判断理由：报告指出“recompute_folder_stats creates a stats row for a folder that may not exist”，但证据表明触发条件罕见或收益有限；按最小改动原则暂不纳入本轮采纳范围。

### R39. （预存） Traditional-character typo in a Simplified-Chinese normative doc

- 来源：bundle_docs_live
- 位置：docs/blueprint/conventions.md:108
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R40. （预存） Dead code: `delete_account()` is implemented but no subcommand exposes it

- 来源：bundle_docs_live
- 位置：docs/skills/kkmail/scripts/kkmail_cli.py:376
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R41. p95 statistic is just the maximum for small run counts

- 来源：bundle_desktop_scripts
- 位置：scripts/benchmark_mailbox.py:165
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R42. Codegen script assumes a 'python' executable exists

- 来源：bundle_desktop_scripts
- 位置：scripts/gen-openapi.sh:10
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R43. pack-linux run() mutates the source tree even for a no-op invocation

- 来源：bundle_desktop_scripts
- 位置：src/desktop/scripts/pack-linux.js:92
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R44. Variable named `is_unread` holds the value sent as the `is_read` filter （预存）

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/MessageList.tsx:129
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R45. Revision id does not match the filename convention used by every other migration

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/db/alembic/versions/20261020_0002_mail_core_unified_schema.py:13
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R46. Test-only synthetic credential constants examined, not real secrets

- 来源：bundle_privacy_history
- 位置：tests/mail_core/conftest.py:25
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R47. Cross-reference only: credential-adjacent findings inside committed review packs

- 来源：bundle_privacy_history
- 位置：docs/reviews/review_20261021_011607/review_summary.md:99
- 优先级：INFO
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R48. （预存）Markdown formatting contract is unenforced

- 来源：bundle_root_ci
- 位置：.md_kx.toml:1
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R49. （预存）OpenAPI document has no servers block and no top-level security

- 来源：bundle_root_ci
- 位置：schemas/openapi.json:2215
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R50. Port parsing is implemented twice with divergent messages

- 来源：bundle_desktop_scripts
- 位置：src/desktop/startup.js:155
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R51. Unused imports in the benchmark module

- 来源：bundle_desktop_scripts
- 位置：scripts/benchmark_mailbox.py:27
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R52. Archived changelog still headed by an [Unreleased] section describing the already-shipped mail-core rewrite （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/CHANGELOG.md:7
- 优先级：INFO
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R53. File/component naming mismatch: SettingsModal.tsx default-exports `SettingsPage`

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/components/SettingsModal.tsx:27
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R54. Fixed e2e login password for the ephemeral local stack examined

- 来源：bundle_privacy_history
- 位置：scripts/run_full_stack_e2e.py:105
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R55. Schema export seeds known placeholder secrets via setdefault

- 来源：bundle_desktop_scripts
- 位置：scripts/export_openapi.py:26
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R56. （预存） Garbled API-key sentence confuses two credential sources

- 来源：bundle_docs_live
- 位置：docs/skills/kkmail/SKILL.md:15
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R57. Inconsistent masking in the git-history privacy section

- 来源：bundle_docs_reviews
- 位置：docs/reviews/review_20261021_011116/bundle_v1_security_v2_correctness.md:468
- 优先级：INFO
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R58. Encrypted-volume requirement points at a moved architecture document

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/security/defaults.py:16
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R59. Historical default OAuth client ID recorded （预存）

- 来源：bundle_docs_archive
- 位置：docs/archive/CHANGELOG.md:219
- 优先级：INFO
- 详细判断理由：问题位于归档历史材料；项目约定归档文件只允許新增，直接改写会破壞历史审计链。当前运行行为不受影响，保留原记录，不采纳原修复建议。

### R60. （预存）External AbortSignal listener is never removed on unsubscribe

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/sseStream.ts:234
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R61. （预存）Nightly cron timezone is nowhere documented

- 来源：bundle_root_ci
- 位置：.github/workflows/scheduled.yml:5
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R62. （预存）Module-level DOMPurify.addHook mutates the shared DOMPurify singleton for every consumer

- 来源：bundle_frontend_state
- 位置：src/frontend/src/lib/mailBody.ts:3
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R63. （预存）Inbox query-key segments share one position with mixed raw/prefixed values

- 来源：bundle_frontend_state
- 位置：src/frontend/src/api/queries.ts:104
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R64. （预存）Runtime apiBase is trusted without any origin/protocol validation

- 来源：bundle_frontend_state
- 位置：src/frontend/src/lib/apiBase.ts:15
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R65. BackupManifest note claims the package still needs encrypting even when it is already sealed

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/backup/package.py:44
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R66. PermanentAuthError is not part of the lazy export surface

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/__init__.py:13
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R67. （预存）Reader srcdoc CSP lacks form-action/base-uri (defense-in-depth only)

- 来源：bundle_frontend_state
- 位置：src/frontend/src/lib/mailBody.ts:120
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R68. Credential-store HKDF uses salt=None

- 来源：bundle_mc_data_crypto
- 位置：src/mail_core/accounts/credentials.py:86
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R69. Reconcile cadence is a magic poll-round count with no rationale

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/sync/delta.py:454
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R70. FastAPI docs and the full OpenAPI schema are served unauthenticated

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/app.py:62
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R71. Token-URI allowlist includes the legacy login.live.com host

- 来源：bundle_mc_providers_sync
- 位置：src/mail_core/providers/oauth.py:44
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R72. /ready discloses schema revision and failure reasons unauthenticated

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/app.py:176
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R73. Callback page CSP relies on unsafe-inline for its one inline script

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/oauth_routes.py:248
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R74. HSTS is sent unconditionally, including plain-HTTP loopback deployments

- 来源：bundle_mc_api_app
- 位置：src/mail_core/api/app.py:100
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R75. Readiness helper bypasses the session factory

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/storage/health.py:12
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R76. A new BlobStore is constructed on every attachment download

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/attachments.py:23
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R77. Trash relies on DB cascade for blob-link cleanup with no ref-count reconciliation in the mutation

- 来源：bundle_mc_api_app
- 位置：src/mail_core/mail/application/mutations.py:175
- 优先级：INFO
- 详细判断理由：影响属于防禦纵深、格式或可维护性提示，未发现当前可触发的功能或安全故障；新增抽象/配置的成本高于现阶段收益，不采纳。

### R78. Review target sha does not exist in the current repository | rubric.md now carries the SUPERSEDED/HISTORICAL banner (:1-3) so the pack reads as archival, and git cat-file on 608e284f75f1da1540138728b3bf328b194a9720 still fails — but :7 still asserts 'HEAD = origin/main = 608e284…' as the reviewed state with no note that the sha is unreachable in current history

- 来源：bundle_regression
- 位置：docs/reviews/review_20261021_034329/\_meta/rubric.md:1
- 优先级：LOW
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R79. BLOCK verdict for an orphaned sha left in the current tree with no three-state marking | Every .md file in the pack now carries the superseded banner, but \_meta.json itself is unchanged: :3 sha b295644… (still not an ancestor of HEAD, merge-base check fails) and :7 verdict BLOCK with no status/superseded field, and the pack still sits under docs/reviews/ rather than docs/archive/reviews/

- 来源：bundle_regression
- 位置：docs/reviews/review_20261021_011116/\_meta.json:3
- 优先级：LOW
- 详细判断理由：问题属于已提交审阅证据或其历史统计；当前轮以新的聚合决策作为权威，直接改写旧报告会削弱审计可追溯性，暂不回写，不采纳。

### R80. Mail iframe sandbox grants allow-popups-to-escape-sandbox to untrusted mail HTML | MAIL_IFRAME_SANDBOX is still exactly 'allow-popups allow-popups-to-escape-sandbox' at :138 and is applied to the mail iframes in src/frontend/src/components/MessageReader.tsx:321,332; docs/guides/security.md:42 documents the same value — the escape token was not dropped (round-2 cross-validation had already narrowed this to overstated/Medium, but the text is unchanged)

- 来源：bundle_regression
- 位置：src/frontend/src/lib/mailBody.ts:138
- 优先级：MEDIUM
- 详细判断理由：该项仅出现在回归核对；frontend_ui bundle 与当前 spec 将此 sandbox 配置判定为符合现行契约，早期复核也已将风险降为被高估的 Medium，现有证据不足以覆蓋已确认安全边界，不采纳。

### R81. 相同历史隐私发现跨 bundle 重复计数

- 来源：review_intensive
- 位置：docs/archive/pending/p027/p028（聚合项）
- 优先级：MEDIUM
- 详细判断理由：本轮聚合已按位置和根因去重；修訂旧轮统计会改写既有审阅记录，当前沒有必要再做一次历史更正。

### R82. 多个模块存在将失败静默转成成功或空结果的共同模式

- 来源：review_intensive
- 位置：src/mail_core、src/desktop/scripts（聚合项）
- 优先级：MEDIUM
- 详细判断理由：五个具体失败点已分别进入采纳或证偽决策；另加全仓规则与 lint 审计会扩大范围，且无法可靠覆蓋不同失败语义。

### R83. PGPASSWORD expansion is not a hardcoded credential

- 来源：bundle_cross_validation, bundle_privacy_history
- 位置：scripts/test_pg_client/pg_dump:27
- 优先级：HIGH
- 详细判断理由：审阅基线的两份脚本都使用 Bash `${PGPASSWORD:-}` 展开：取环境变量值，未设置时为空。15 个字符是 shell 语法，不是固定密码；无需轮换测试数据库密码。审阅报告把变量表达式误认成硬编码凭据。

### R84. PGPASSWORD expansion is not a hardcoded credential

- 来源：bundle_cross_validation, bundle_privacy_history
- 位置：scripts/test_pg_client/pg_restore:17
- 优先级：HIGH
- 详细判断理由：审阅基线的两份脚本都使用 Bash `${PGPASSWORD:-}` 展开：取环境变量值，未设置时为空。15 个字符是 shell 语法，不是固定密码；无需轮换测试数据库密码。审阅报告把变量表达式误认成硬编码凭据。

### R85. 归档架构文档的直接编辑不符合写权约定

- 来源：bundle_cross_validation, bundle_docs_archive
- 位置：docs/archive/legacy_architecture/mail-core-architecture.md:7
- 优先级：HIGH
- 详细判断理由：修复建议要求改写 docs/archive 内已有文件，违反 AGENTS.md“内部文件只准新增”的约定；live blueprint 已将该文档标为历史规范。保留归档原文，不采纳直接编辑建议。

### R86. 未读取的 shuttingDown 标志

- 来源：bundle_desktop_scripts
- 位置：src/desktop/main.js:50
- 优先级：LOW
- 详细判断理由：该标志只写入、不读取，没有运行行为影响。与 R26/R27/R31/R35/R40 同属死变量/死代码，按一致的最小改动原则不采纳。

### R87. 未使用的 providerBadge 导出

- 来源：bundle_privacy_history
- 位置：src/frontend/src/store/mailStore.ts:155
- 优先级：LOW
- 详细判断理由：当前生产代码没有调用该函数；清理不会修复可观察行为。与 R26/R27/R31/R35/R40 同类，按一致的最小改动原则不采纳。

### R88. 未使用的 MAIL_LIST_PREFIX 常量

- 来源：bundle_privacy_history
- 位置：src/frontend/src/api/queries.ts:63
- 优先级：LOW
- 详细判断理由：当前生产代码没有引用该常量；清理不会修复可观察行为。与 R26/R27/R31/R35/R40 同类，按一致的最小改动原则不采纳。

### R89. 未使用 providerBadge 导致的颜色不一致不可见

- 来源：bundle_frontend_state
- 位置：src/frontend/src/store/mailStore.ts:164
- 优先级：LOW
- 详细判断理由：providerBadge 没有生产调用，报告中的 badge/color 差异不会影响当前界面。该观察属于未使用 helper 的延伸，不构成独立运行故障，不采纳。

### R90. 未使用的 schemaTypes 转发模块

- 来源：bundle_frontend_ui
- 位置：src/frontend/src/types/schemaTypes.ts:1
- 优先级：LOW
- 详细判断理由：生产导入使用 api/schemaTypes；该转发模块没有调用方。清理只减少冗余入口，不修复现有行为，与同类死代码项保持一致，不采纳。

### R91. 拒绝撤销或轮换历史记录中的第三方 Outlook 凭据

- 来源：用户后续决策
- 位置：历史 `outlook_mail_reader.py` 的 `EMAIL`、密码与 refresh token；远端历史
- 优先级：CRITICAL
- 详细判断理由：用户确认该账户不属于本人，并要求将撤销/轮换记为拒绝。不得代第三方登录或更改账户凭据；凭据当前有效性未知，由账户所有者处理。

### R92. 拒绝向 GitHub Support 提交 PR 历史与缓存清理请求

- 来源：用户后续决策
- 位置：GitHub `refs/pull/1/head` 及其缓存视图
- 优先级：HIGH
- 详细判断理由：用户要求将该外部支持请求记为拒绝。远端分支与 tag 历史已清理，但 GitHub 管理的 PR 引用仍指向旧历史；未向 GitHub Support 发送请求。
