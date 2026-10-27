> [!NOTE]
> **已关闭 / HISTORICAL — 后续状态注记（2026-10-27 补）**
> 本报告的 BLOCK 结论为 2026-10-25 审阅时点（基线 29dcd3a4a080a23423a32b02cce37ee546d48c97）的结论，不代表当前状态。采纳处置见同目录 `adoption_decision.md`；后续状态见 `docs/reviews/review_20261026_*` 各包与 `docs/handoff.md`。

# Intensive Review — https://github.com/TuTouPower/kkmail (all, round 3) @ 29dcd3a4a080a23423a32b02cce37ee546d48c97 2026-10-25

## Summary

- Scope: 739 whitelisted files / 84,882 lines (1,067 tracked files, ~133k lines), 175 bundle.py bundles merged into 11 review units + central privacy/history probes + regression pass; 8 perspectives per code unit; docs/tooling units probe-driven with targeted full reads (method stated in their Coverage notes). Repo is PUBLIC; history was fully rewritten before this HEAD (no merge base vs round-2 sha da57df7), so the history scan covers the NEW history.
- Findings (aggregate.py, deduped): Critical=8 High=57 Medium=153 Low=195 Info=41, total 454
- Verdict: **BLOCK** (deterministic matrix: any Critical -> BLOCK)
- Cross-validation (falsify pass over all 67 Critical/High: C10/H57 raw): AGREE 62 (C8/H54), DUPLICATE 3 (C2/H1 — the regression addendum's intentional re-files of the two still-present round-2 Criticals, plus one PII double-file), CHALLENGED 1 (High, remote_ops.py:35 — CAS counter-evidence, confidence adjusted to 35), OVERSTATED 1 (High, /health instance-token leak — fits Medium, confidence 70). All 8 deduped Criticals are AGREE. SURFACE patterns: review packs are now the main republication channel for the historical credential recipe + verbatim legacy key; a 'degrade to green' pattern across five subsystems (pack soft-ok, bare-except swallow, flag-FETCH [] fall-through, pg_restore exit-1 fall-through, smoke-test silent skip).

## Regression vs round 2 (baseline: review_20261021_064335, C8/H50, BLOCK)

- Round-2 Critical: **FIXED 6 / STILL PRESENT 2 / CHANGED 0 / MOOT 0**. Named checks: (i) stale 011116 pack presenting fixed Criticals as current — FIXED (SUPERSEDED/HISTORICAL banners now on the pack, applied consistently to 011116/034329/040521 packs); (ii) sample encryption keys quoted verbatim in 011116 — FIXED (all values masked '\*\*\*', structurally verified); (iii) 040521 credential retrieval recipe + non-rotation decision — **STILL PRESENT, both halves** (recipe now at bundle_v1_security.md:21, decision at summary_verification_report.md:38; the credential commit is still reachable via tags at HEAD; round-2's uncommitted redactions were lost in the history rewrite, exactly as feared); (iv) password-reset flow broken for DB-backed auth — FIXED (docs/guides/troubleshooting.md rewritten around auth_credentials; verified against src/mail_core/security/auth.py priority chain; residual: docs/guides/security.md still describes pre-DB storage — filed as a still-present High).
- Round-2 High: **FIXED 33 / STILL PRESENT 9 / CHANGED 7 / MOOT 1**. Still-present includes: pack count/scope falsities in old packs, security.md stale password-storage description, unpinned base images/deps (Dockerfile.mail-core:2), mail iframe allow-popups-to-escape-sandbox (mailBody.ts:138), and others — full per-item lines in bundle_regression.md.
- Round-2 validation items (7): **FIXED 4 / STILL PRESENT 3**. Fixed: SettingsModal TS2322 (confirmed by coordinator's clean tsc -b --force run), listDate TZ hermeticity, oxlint warnings (coordinator rerun: 0/0 under --deny-warnings), backup-verify .verify_extract leftover. Still present: markReadOptimistic/setReadOptimistic unbounded fan-out (queries.ts:281, re-filed as High), Gmail 'historyid' substring error mapping (gmail.py:71), tsconfig.node.json non-strict.

## Validation (run by coordinator at 29dcd3a, 2026-10-25)

- Backend pytest, unit mode (KKMAIL_TEST_MODE=unit, PYTHONPATH=src): **358 passed, 211 skipped, 3 failed** in 63.6s. Failures: (1) test_accounts_api_unit.py::test_create_account_serializes_slotted_dto_mock — 400 vs 200, SSRF guard rejects test host 'imap.kkmail.test'; (2) test_medium_providers_sync_blobs.py::test_build_provider_imap_json_credentials_unpack — same SSRF guard raises on 'mail.test' (factory.py:73); whether (1)/(2) also fail under the project's own PG test runtime is unverified (guard behaviour depends on DNS resolution of .test hosts); (3) test_kkmail_cli.py::test_session_cache_custom_path_does_not_modify_parent_permissions — parent dir mode became 0o760, expected unchanged 0o755: a plain logic failure.
- Backend full mode (scripts/run-mail-core-tests.sh / test_pg_runtime) NOT run: it requires an owned PostgreSQL runtime; none exists in this sandbox and plain `pytest tests/` aborts in conftest demanding KKMAIL_TEST_MODE=unit or a DB runtime. This is a coverage limitation, recorded as such.
- repo_template contract tests: **150 passed**, 374 deselected.
- Frontend (npm ci, 154 packages): npm test = vitest **303 passed / 1 failed** (304 tests, 42 files) + openapi generated-schema check PASS + CSS variable check PASS; failing test: MessageReader.test.tsx > 'does not crash and renders cleanly when non-mail queries are present in QueryCache (AC-001, AC-002)' — component renders an unexpected role=alert element. **tsc -b --force: exit 0, clean.** oxlint (incl. --deny-warnings): **0 warnings, 0 errors** over 95 files.

## Critical (8, deduped; all AGREE after cross-validation)

全文见 [review_intensive.md](review_intensive.md)「Findings（deduped, sorted by Severity × Confidence）」节（单一权威）；本摘要不复写全文，配方类条目在此仅以计数呈现。

## High (57, deduped)

全文见 [review_intensive.md](review_intensive.md)「Findings（deduped, sorted by Severity × Confidence）」节（单一权威）；本摘要不复写全文，配方类条目在此仅以计数呈现。

## Strengths (one per bundle, see each bundle report for full lists)

- (bundle_desktop_scripts.md) Electron posture is genuinely good: contextIsolation on, nodeIntegration off, sandbox on, webviewTag off and will-attach-webview denied, minimal preload surface (platform + versions only), navigation/window-open gated, single-instance lock, and a restrictive CSP replacing any upstream header.
- (bundle_docs_archive.md) No live secrets in a 274-file public archive: zero token shapes, zero literal passwords/keys, zero private keys — despite the archive documenting a credential-handling product in unusual depth.
- (bundle_docs_live.md) Troubleshooting's password-reset section is a model fix: it names the authoritative source, gives two working procedures, and matches the bootstrap code path-for-path.
- (bundle_docs_reviews.md) Re-check (i) PASSED: review_20261021_011116/review_intensive.md now opens with a SUPERSEDED/HISTORICAL banner (lines 1-3), and the same banner was applied consistently to every file in the 011116, 034329 and 040521 packs, directly implementing the round-2 decision recorded in the 064335 decisions file.
- (bundle_frontend_state.md) CSRF design is genuinely strong: unsafe requests are never sent without a token, the token fetch is singleflight, a CSRF-shaped 403 triggers exactly one refetch-and-retry, and 401 centrally clears the token and broadcasts UNAUTHORIZED_EVENT (client.ts).
- (bundle_frontend_ui.md) Mail HTML security is done properly (spec AC-005): MessageReader renders the body only via an iframe with `sandbox={MAIL_IFRAME_SANDBOX}` = `allow-popups allow-popups-to-escape-sandbox` (no allow-scripts, no allow-same-origin), `referrerPolicy="no-referrer"`, a srcdoc built by DOMPurify sanitization plus an in-frame CSP (`default-src 'none'`), and remote images blocked by default with a per-message opt-in that resets on message switch. No `dangerouslySetInnerHTML` anywhere in the unit (grep-verified).
- (bundle_mc_api_app.md) Auth is applied uniformly: accounts/mail/SSE routers are mounted with `Depends(require_auth)`, CSRF uses `secrets.compare_digest` with an API-key bypass that is explicit, and login has a failure limiter with Retry-After (spec AC-001/002/005 shape is respected at this layer).
- (bundle_mc_data_crypto.md) Blob crypto (blobs/crypto.py): chunked AES-256-GCM with per-frame nonce derivation, final-flag in AAD (truncation/reorder detectable), random nonce prefix per blob, and fail-closed key loading with no dev fallback — matches spec and test_blob_keyring_required.
- (bundle_mc_providers_sync.md) IMAP remote_ids are namespaced as UIDVALIDITY␟folder␟UID (imap.py), eliminating the classic cross-folder UID collision, and UIDVALIDITY changes raise CursorInvalidError for a controlled rebuild instead of silent corruption.
- (bundle_repo_tooling.md) No shell injection surface anywhere: every subprocess call is argv-list form, git calls consistently use timeouts in the core package (git_ops wraps TimeoutExpired into TaskDataError), and user-controlled identifiers (slug/tid/pNNN/dNNN) are fullmatch-validated before reaching paths or git args in nearly every entry point.
- (bundle_root_ci.md) Workflows use plain `pull_request` (no pull_request_target anywhere) and the only `${{ }}` interpolation inside a `run:` block is the `needs.*.result` enum comparison in ci-status (ci.yml:180-183) — no script-injection surface; top-level `permissions: contents: read` on both workflows.

## Spec Compliance

- Per-unit spec-compliance sections live in each bundle\_\*.md. Cross-cutting: live spec ACs in docs/specs/inbox_ui_and_search.md (AC-002 100/page + load-more button; AC-006 collapse-to-icon-rail) are superseded by shipped behaviour (50/page IntersectionObserver; full sidebar removal) yet still marked current; SSE streams are never re-authorized after logout/password change (auth spec AC-004 partial); GET message detail mutates state/enqueues jobs (AC-005 spirit).

## Appendix — Traceability

- Skill: intensive-review (user-uploaded SKILL.md); packing by bundle.py (739 files / 175 bundles), aggregation by aggregate.py (454 deduped, review_intensive.md). Units/meta: \_meta/units.json, \_meta/\_meta.json; stage checkpoints: \_meta/progress.log.
- Reports: bundle\_<unit>.md x11, bundle_privacy_history.md (central probes), bundle_regression.md + bundle_regression_addendum.md (round-2 regression), bundle_cross_validation.md (falsify pass).
- Coverage limits: docs_reviews/docs_archive/repo_tooling units were probe-driven with targeted full reads (stated in their Coverage notes); history secret scan covered git log --all of the rewritten history with -G/-S shape scans + revision sampling (Bearer literals found were all synthetic test fixtures, examined and dismissed in bundle_privacy_history.md); remote (GitHub) reachability of pre-rewrite commits was NOT network-verified — local-clone reachability via tags was verified; screenshots under img//assets were not OCR-scanned.
- Process note: all stages (units -> probes -> regression -> cross-validation -> validation -> aggregate -> summary) completed in this run; checkpoints in \_meta/progress.log. No source files were modified by the review; writes are confined to this OUTDIR (plus gitignored build artifacts from validation: src/frontend/node_modules via npm ci, and the pre-existing persistent venv at <local-path>).
