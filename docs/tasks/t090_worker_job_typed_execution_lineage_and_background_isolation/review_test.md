# Task review t090（reviewer_focus: 测试）

- task：`t090_worker_job_typed_execution_lineage_and_background_isolation`
- spec：`docs/tasks/t090_worker_job_typed_execution_lineage_and_background_isolation/task.md`
- diff_anchor：`452dc8f3d7308f2651a05aa16b2132508f6927dd`
- target：`git diff 452dc8f3d7308f2651a05aa16b2132508f6927dd`
- round：1
- reviewed_at：2026-11-25T19:51:41+08:00

## Findings

### t090_test_f001 - `engine.py` 与 `remote_push.py` 部分重试/重建分支未覆盖 `execution_origin="background"`

- 严重度：minor
- 锚点：AC-003（覆盖扩展建议，不阻断：核心入口及 `delta.py`、`complete_job`、`reschedule_job`、`sync_folder_metadata(exhausted=True)` 均已实测）
- 位置：`tests/mail_core/test_t090_execution_origin.py:285-353`（`test_t090_background_continuations_rebuilds_and_push_fallback_inherit`）、`tests/mail_core/test_sync_inbox_first.py:442-502`
- 问题：`test_t090_background_continuations_rebuilds_and_push_fallback_inherit` 覆盖了 `sync_folder_delta` 的 `LeaseBusy` / `RateLimitedError` / `EndpointCircuitOpenError` / `exhausted=False` / `CursorInvalidError` 与 `sync_folder_metadata(..., exhausted=True)` 的后台血缘继承，但 `sync_folder_metadata` 自身的 `LeaseBusy`、`RateLimitedError`、`CAPACITY_ERRORS`、`CursorInvalidError` 重建、`exhausted=False`、`full and request_id` 分支，以及 `sync_account_folders` 的 `CAPACITY_ERRORS` / `RateLimitedError` 分支和 `push_remote_operations` 的重试/分批续跑分支，在现有测试（如 `test_sync_inbox_first.py`、`test_t064_batched_remote_writeback.py`）中仅传入 `execution_origin="foreground"`；若后续上述分支遗漏透传 `execution_origin=origin`，现有测试集不会直接捕获后台退化风险。
- 建议：在 `tests/mail_core/test_t090_execution_origin.py` 中参数化补充 `execution_origin="background"` 下 `sync_folder_metadata`（`LeaseBusy`/`RateLimitedError`/`CursorInvalidError`/`exhausted=False`）、`sync_account_folders`（`CAPACITY_ERRORS`/`RateLimitedError`）与 `push_remote_operations` 续跑的血缘断言。

### t090_test_f002 - 个别入口契约直接调用私有方法或未显式断言写入的 `execution_origin` 值

- 严重度：minor
- 锚点：AC-002、AC-003（覆盖与测试方式改进建议，不阻断）
- 位置：`tests/mail_core/test_t090_execution_origin.py:247`、`tests/mail_core/test_t090_execution_origin.py:368`、`tests/mail_core/test_imap_id_handshake.py:131-155`、`tests/mail_core/test_accounts_run_in_session_a247.py:66-76`
- 问题：`test_t090_periodic_patrol_and_idle_background_isolation` 直接调用了 `IdleWatcherManager._enqueue_delta(watch)`（不过公开的 `IdleWatcherManager.start()` / `stop()` 建连补偿与 IDLE 唤醒全链路已在 `tests/mail_core/test_t090_coalescing_and_fencing.py:293-363` 补足）；`test_t090_background_continuations_rebuilds_and_push_fallback_inherit` 直接调用私有辅助函数 `remote_push_mod._persist_move_remote_state(...)`，未通过公开 `push_remote_operations` 驱动未知目标目录发现兜底路径；此外 `create_account_app`（`test_imap_id_handshake.py:131-155`）、`sync_account_app`（`test_accounts_run_in_session_a247.py:66-76`）、`oauth_routes._enqueue_sync_best_effort` 与 `archive.resume_quota_paused_archives` 目前未在断言中校验具体的 `execution_origin` 枚举值（当前由必填参数契约防止省略）。
- 建议：通过公开 `push_remote_operations` 移动回写场景覆盖未知目录发现兜底入队为 `background`，并在账号创建/OAuth/按账号同步/配额恢复测试中补充对 `execution_origin` 值的显式断言。

## 结论

- 改测方向复核：无「迁就实现」的改测。逐类核查 `git diff 452dc8f3d7308f2651a05aa16b2132508f6927dd -- tests/` 结果如下：
    - 固化旧 `payload["background"]` / `sync_context_payload` 缺陷的旧测试已按 spec 要求整体替换并写明原因：`tests/mail_core/test_account_health_state_machine.py:221-243`（`test_resolve_sync_context_reads_top_level_background_marker` 替换为 `test_resolve_sync_context_uses_typed_column_and_ignores_payload_marker`）、`tests/mail_core/test_sync_backend_handler_isolation.py:44-105`（`test_explicit_background_marker_and_scope_lineage` 与 `test_sync_context_payload_never_emits_background_marker` 替换为 `test_execution_origin_column_and_scope_consistency` 与 `test_sync_request_payload_emits_only_request_correlation`）、`tests/mail_core/test_sync_background_lineage.py:247-311`（替换为 `test_resolve_sync_context_uses_origin_and_scope_consistently` 与 `test_sync_request_payload_carries_correlation_without_marker`），均保留或增强了全部有效边界断言并新增缺失 `execution_origin` 报错校验。
    - 断言增强：`tests/mail_core/test_accounts_api_unit.py:266-306` 新增 `assert execution_origin == ExecutionOrigin.FOREGROUND`；`tests/mail_core/test_schema_pg.py:780-789` 新增 PG 级非法值 `ValueError`/`IntegrityError` 与缺省 `NOT NULL` 拒绝测试；`tests/mail_core/test_sync_background_lineage.py:357, 370, 391` 新增 `execution_origin == ExecutionOrigin.BACKGROUND.value` 断言。
    - 规格变更适配：`tests/mail_core/test_worker_scheduler.py:84-87` 在 `test_ac001_schedules_overdue_inbox` 将原先对 `payload["background"] == True` 的断言调整为 `assert job.execution_origin == ExecutionOrigin.BACKGROUND.value` 与 `assert job.payload == {"folder_id": str(folder_id)}` 并附 `# t090:` 说明（同时在 `test_ac002_staggers_multiple_accounts` 补充相同断言），反映的是已批准的 spec 契约迁移（禁止 `payload["background"]` 并提升为一等公民列），未放宽或迁就实现缺陷。
    - 其余约 50 个既有测试文件仅在构造 `WorkerJob` 或调用 `enqueue_job` / `enqueue_account_sync` / `sync_account_folders` / `sync_folder_metadata` / `sync_folder_delta` / `push_remote_operations` / `_merge_into_pending_job` 时补齐必填关键字参数 `execution_origin`，未删除或弱化既有断言。
- 本轮新发现：2 条（均为 `minor`：`t090_test_f001`、`t090_test_f002`；0 条 `critical` / `important`）
- 未进表的提示：
    1. 静态测试卫生与复杂度核查：3 个新增测试文件均 `< 600` 行（`tests/mail_core/test_t090_migration_0006.py` 166 行、`tests/mail_core/test_t090_coalescing_and_fencing.py` 452 行、`tests/mail_core/test_t090_execution_origin.py` 507 行）；新增测试函数分支圈复杂度均 `CC < 15`（最大 `cc_branch=7`，位于 `test_t090_idle_watcher_real_lifecycle_enqueues_background`）；`git diff 452dc8f3d7308f2651a05aa16b2132508f6927dd -- tests/` 中 0 处新增 `# type: ignore`、`.skip` / `.only`、`eslint-disable`、`@ts-ignore` 或恒真断言（仅 3 个新增 PG 测试文件含标准文件级 `pytestmark = pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"), ...)`，在 PG 门禁运行时未触发跳过）。
    2. 范围外历史测试观察：`tests/mail_core/test_migration_validation.py:94-116`（本 task 未改动）的 `test_alembic_chain_has_single_head` 从 `UNIFIED_BASELINE_REVISION` 而非 `CURRENT_HEAD_REVISION` 开始沿 `down_revision` 追溯并断言 `len(visited) == 1`，因此本身未遍历 `0002..0006` 线性链；本轮已由 `tests/mail_core/test_t090_migration_0006.py:146-147` 独立断言 `CURRENT_HEAD_REVISION == "20261125_0006"` 与 `get_heads() == ["20261125_0006"]` 弥补。另 `tests/mail_core/test_sync_backend_handler_isolation.py:1-13` 模块顶部旧注释仍提及顶层 `background` payload marker，建议后续顺手清理。
    3. 独立复跑验证结果（均在当前 worktree 只读执行通过）：
        - 聚焦真实 PostgreSQL 套件：`./scripts/run-mail-core-tests.sh run --no-cov -k "test_t090 or test_migration_validation or test_migrate_to_unified_baseline or test_sync_background_lineage or test_sync_backend_handler_isolation or test_account_health_state_machine or test_r4adopt_p28_a347 or test_worker_scheduler or test_schema_pg"` → `102 passed, 2163 deselected, 1 warning`（0 failed, 0 skipped）。
        - 受改动单测补跑：`KKMAIL_TEST_MODE=unit PYTHONPATH=src .venv/bin/pytest --no-cov -q tests/mail_core/test_accounts_api_unit.py tests/mail_core/test_accounts_run_in_session_a247.py tests/mail_core/test_medium_providers_sync_blobs.py tests/mail_core/test_sync_engine_failure_unit.py tests/mail_core/test_worker_capacity_retry_after_a18.py tests/mail_core/test_worker_invalid_payload.py tests/mail_core/test_worker_payload_gc_backup_a253.py` → `84 passed, 1 warning`。
        - `docs/blueprint/testing.md` `test_cmd` 全部 4 项：`.venv/bin/pytest .repo_template/tests -q -m contract`（`389 passed, 1 skipped`）、`(cd src/frontend && npm test && npx tsc -b && npm run build)`（56 文件 597 tests + `openapi:check` + `css:check` + `tsc -b` + `vite build` 全过）、`(cd src/desktop && npm test)`（12 suites 通过；Electron OAuth 集成按未设外部凭据跳过）、`python3 scripts/check_doc_sensitive.py docs --check`（35 文件 0 违规）。
        - 未全量重跑范围：被 `-k` 过滤掉的其余 2163 条 PostgreSQL 用例及完整 E2E 套件未由 reviewer 重跑；核查实施侧在末次测试编辑（19:11:19）后于 `.scratch/test_runs/f37b6d720ccf43bea362ce7366a22fed/junit.xml`（19:11:45）产出的全量运行产物显示 `tests="2265" errors="0" failures="0" skipped="2"`（2 条环境跳过为 `/dev/shm not writable` 与 `explicit Electron integration mode`）。
- 总体判断：全部 6 条 AC 均获可信测试或文档/门禁验证支撑，无未解决 `critical` / `important` finding，仅 2 条覆盖扩展类 `minor` 建议，判定 PASS。
- 系统性 follow-up：无（已只读检查 `.repo_template/scripts/task.py list`，下游故障模型重构已立项为 `t091`）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`tests/mail_core/test_t090_migration_0006.py:36-166` 在独立 PostgreSQL 库上对 10 类存量行验证 `20261124_0005` → `head`（`20261125_0006`）回填、非空与 `ck_worker_jobs_execution_origin` 约束拦截及 `downgrade 20261124_0005` → `upgrade head` 往返，`tests/mail_core/test_schema_pg.py:780-789` 与 `tests/mail_core/test_migration_validation.py:152-415` 验证 `downgrade base` → `upgrade head` 及 `compare_metadata` 0 drift，且全部 102 条聚焦 PG 用例实测通过。
- AC-002：TICK-VALID，re_verified。`tests/mail_core/test_t090_execution_origin.py:120-190` 实测省略或传入非法 `execution_origin` 在 `enqueue_job` / `enqueue_account_sync` 立即抛 `TypeError` / `ValueError`，并校验手扫、`set_message_read`、`SyncRequest(background=True)` 与 `sync_message_body` 显式写入对应血缘；`tests/mail_core/test_accounts_api_unit.py:266-306` 与 `tests/mail_core/test_worker_scheduler.py:84-87, 144-145` 亦已实测通过。
- AC-003：TICK-VALID，re_verified。`tests/mail_core/test_t090_execution_origin.py:192-507`、`tests/mail_core/test_t090_coalescing_and_fencing.py:113-407` 与 `tests/mail_core/test_sync_background_lineage.py:347-452` 在真实 PostgreSQL 下覆盖周期轮询、`patrol` 巡检、真实 `IdleWatcherManager.start()` 建连补偿与 IDLE 唤醒，以及 `LeaseBusy`、`RateLimitedError`、`EndpointCircuitOpenError`、双支 `FencingMismatch`、多页未穷尽、`CursorInvalidError` 重建与 `complete_job` 后继派生保留后台血缘并在传输超时下保持 `connectivity_state == "connected"`。
- AC-004：TICK-VALID，re_verified。`tests/mail_core/test_t090_coalescing_and_fencing.py:409-452`、`tests/mail_core/test_t090_execution_origin.py:446-507` 与 `tests/mail_core/test_sync_background_lineage.py:454-490` 在真实 PostgreSQL 下实测前台 `SyncRequest` / 前台后继任务在连续传输超时窗口下由 `degraded` 升级至 `unreachable` 且不污染凭据态，同时验证后台 `PermanentAuthError` 仍按契约将 `credential_state` 置为 `invalid` 并禁用同步。
- AC-005：TICK-VALID，trust_prior。reviewer 已实测全部 4 项 `test_cmd` 门禁与 102 条聚焦真实 PostgreSQL 用例（含 `test_migration_validation` 与 `test_migrate_to_unified_baseline` 全部 35 例）通过；其余 2163 条被 `-k` 过滤的 PG 用例未重跑全量，依据实施侧在末次代码/测试编辑后产出的 `.scratch/test_runs/f37b6d720ccf43bea362ce7366a22fed/junit.xml`（2265 tests, 0 failures, 0 errors, 2 environment skips）。
- AC-006：TICK-VALID，re_verified。已逐行核对 `docs/specs/mail_sync_and_storage.md:4, 27`（front matter `tasks` 登记 `t090` 并补充规范条文）及 `docs/blueprint/architecture.md:132`、`docs/blueprint/conventions.md:167`、`docs/blueprint/testing.md:41-42, 83, 214-215` 同步更新，且 `python3 scripts/check_doc_sensitive.py docs --check` 报 0 违规。

coverage = 5 / 6

reviewed_scope: 97b54d5e4f037fb6

verdict: PASS
