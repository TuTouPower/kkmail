# Validation（真跑测试）— 第四轮 intensive-review

- 被审 HEAD：`11bfa52a27018fe46f2ed03f784e19439cfd950d`（11bfa52a）
- 对照基线：`284233a7`（上一轮收尾；任务给定基线数字：后端 812 passed / 280 skipped / 3 failed、前端 446 全过、tsc 绿）
- 运行时间：2026-10-27 02:19–02:27 CST（本机，仓库根 `.venv`，Python 3.12.3）
- 测试入口确认口径（与既往轮次 `.scratch/fix_progress.log` 一致）：
  - 后端 unit：`scripts/run-mail-core-tests.sh unit`（内部经 `scripts/test_pg_runtime.py unit` 以 `KKMAIL_TEST_MODE=unit` 跑 `.venv/bin/python -m pytest tests -q -ra --cov=mail_core ...`）
  - 前端：`src/frontend/package.json` 的 vitest（`./node_modules/.bin/vitest run`，在 `src/frontend/` 下执行）
  - tsc：`src/frontend` 的 `tsc -b`（`./node_modules/.bin/tsc -b`，即 `npm run build` 的类型检查部分，与既往审阅证据口径一致）

## 1. 后端 unit 测试

- 完整命令：`TZ=Asia/Shanghai scripts/run-mail-core-tests.sh unit`（仓库根执行）
- 退出码：**1**
- 确切数字（pytest 汇总行 + 本次运行 `test_summary.json` 双重核对）：**807 passed / 15 failed / 280 skipped**，共收集 1102 项，耗时 123.52s
- 与基线对照：基线 812/3/280、收集 1095；HEAD 多收集 7 项（t056/p058/p059 新增），passed −5、failed +12、skipped 不变。

失败用例清单（15 条全列）：

1. `tests/mail_core/test_accounts_api_unit.py::test_create_account_serializes_slotted_dto_mock`
2. `tests/mail_core/test_gmail_sync_strategy_and_timeout.py::test_sync_account_folders_pauses_gmail_virtual_folders`
3. `tests/mail_core/test_gmail_sync_strategy_and_timeout.py::test_worker_transient_network_timeout_does_not_fail_account`
4. `tests/mail_core/test_gmail_sync_strategy_and_timeout.py::test_worker_permanent_auth_error_still_fails_and_disables_account`
5. `tests/mail_core/test_medium_providers_sync_blobs.py::test_build_provider_imap_json_credentials_unpack`
6. `tests/mail_core/test_outbox_retention_unit.py::test_alembic_chain_head_is_0026`
7. `tests/mail_core/test_remote_push_capacity_coalesced.py::test_capacity_coalesced_followup_survives_settlement`
8. `tests/mail_core/test_search_like_escape.py::test_search_escapes_like_metacharacters_only_for_ilike_branches`
9. `tests/mail_core/test_search_recipients.py::test_recipient_address_in_search_and_account`
10. `tests/mail_core/test_settings_store.py::test_build_provider_logs_timeout_lookup_failure_with_account_context[injected_session]`
11. `tests/mail_core/test_settings_store.py::test_build_provider_logs_timeout_lookup_failure_with_account_context[session_factory]`
12. `tests/mail_core/test_sync_execution_unit.py::test_alembic_chain_single_head_is_0026_and_linear`
13. `tests/mail_core/test_sync_full_scan_metadata_reuse.py::test_full_request_reuses_root_generation_while_metadata_in_flight`
14. `tests/mail_core/test_sync_shared_full_scan.py::test_shared_full_requests_complete_only_after_metadata_and_reconcile`
15. `tests/mail_core/test_worker_loop.py::test_handle_job_sanitizes_error_in_update_account_sync_status`

## 2. 前端测试（vitest）

- 完整命令：`cd src/frontend && ./node_modules/.bin/vitest run`
- 退出码：**0**
- 确切数字：**46 个测试文件全部通过，448 tests passed / 0 failed**（Duration 102.80s）
- 与基线对照：基线 446 全过；HEAD 448 全过（+2，为 p058/p059 扩充的 Sidebar 等用例），无新失败。

## 3. TypeScript（tsc）

- 完整命令：`cd src/frontend && ./node_modules/.bin/tsc -b`
- 退出码：**0**，无任何诊断输出
- 结论：**tsc 绿**，与基线一致。

## 4. 新失败的既存性判定（基线 worktree 对照实跑）

方法：`TZ=Asia/Shanghai git worktree add /tmp/kkmail-baseline-284233a7 284233a7`，在该 worktree 内链入主仓库 `.venv` 后以同一口径跑全量 unit（`scripts/run-mail-core-tests.sh unit`，附加参数为上述失败子集 nodeid，pytest 去重后实际仍为全量）。基线运行的 `test_summary.json` 实测：**收集 1095、812 passed / 3 failed / 280 skipped**，与任务给定基线数字完全一致，对照有效。基线 3 个失败为：

- `test_accounts_api_unit.py::test_create_account_serializes_slotted_dto_mock`
- `test_medium_providers_sync_blobs.py::test_build_provider_imap_json_credentials_unpack`
- `test_system_health.py::test_system_health_metrics_calculation`（此条在 HEAD 已不失败）

对照后判定：

### 既存失败（2 条，非本轮新增）

- #1 `test_create_account_serializes_slotted_dto_mock`：基线同样失败，`imap.kkmail.test` 被判 private/loopback（SSRF protection）返回 400，本机 DNS/环境性失败。
- #5 `test_build_provider_imap_json_credentials_unpack`：基线同样失败，`mail.test` 同样触发 SSRF protection；既往多轮 fix_progress 亦记为 pre-existing env failure。

### 新失败（13 条，基线之外；基线全量对照中均通过或基线不存在）

基线已存在且基线通过、HEAD 失败（9 条）：

- #6、#12 alembic 链头断言 ×2：断言 head 为 `20261026_0026`，实际 `20261027_0027`（p059 新增迁移 0027，两处断言未同步更新）。
- #8 `test_search_like_escape`：断言 `ESCAPE E'\\'` 出现 2 次，实际 3 次（p059 在搜索语句新增 `to_text` ILIKE 分支，断言未同步）。
- #7、#13、#14 同步类 ×3：SQLite 报 `no such column: recipient_addresses`（p059 给 `Account` 新增 `recipient_addresses` 列，`INSERT INTO accounts ... RETURNING recipient_addresses`；这些用例的 SQLite 建表夹具仍是旧列集）。
- #10、#11 `test_settings_store` timeout ×2：断言 `provider.timeout == 30.0`，实际 `60.0`（t056 将默认 fetch timeout 由 30s 改为 60s，该测试未同步）。
- #15 `test_worker_loop`：断言 `update_account_sync_status` 被调用 1 次，实际 0 次（t056 改动 `worker/handlers.py` 后行为变化）。

基线不存在的新测试文件、自身即失败（4 条）：

- #2、#3、#4 `test_gmail_sync_strategy_and_timeout.py`（t056 新增，文件共 6 条、3 条失败）：直接调用 `get_session_factory()`，在 unit 模式下抛 `DatabaseConfigError: MAIL_CORE_DATABASE_URL is required`——属 PG 依赖但未做 PG 门控 skip。
- #9 `test_search_recipients.py::test_recipient_address_in_search_and_account`（p059 新增，该文件唯一用例）：同一 `DatabaseConfigError`，PG 依赖未门控。

判定结论一句话：**15 个失败中 2 个为基线既存环境失败，13 个是基线之外的新失败（9 条既有测试被 t056/p059 改动打破、4 条为 t056/p059 新增测试自身未过），另基线第 3 个失败 test_system_health 在 HEAD 已消失。**

对照 worktree 已用 `TZ=Asia/Shanghai git worktree remove --force /tmp/kkmail-baseline-284233a7` 清理干净（`git worktree list` 仅剩主工作区及一条与本任务无关的既存 prunable 记录）。

## 5. PG 门控类测试

- unit 模式按设计不执行 PG 套件：本次 280 skipped 中绝大多数为 `MAIL_CORE_DATABASE_URL not set` / `PG required`，属预期跳过，不是伪装通过。
- 全量门禁实测：`TZ=Asia/Shanghai scripts/run-mail-core-tests.sh run` → **退出码 2**，在 allocate 阶段即失败：`provide operator-supplied KKMAIL_TEST_PG_PASSWORD (check .env.test ...)`；且本机 `docker: command not found`（无 Docker），`scripts/test_pg_runtime.py` 的 `guard_database()` 要求 Docker 所有的专用测试 PG 运行记录，无法合法启动。因此 PG 门控类测试在本机 **未跑通、未执行**，与既往轮次 ENV NOTE 口径一致（不伪造所有权、不冒充已验）。便携 PG 旁路 harness 不属本 validation 任务口径，未做。

## 6. 工作区核对

三项跑完及 worktree 清理后 `git status --porcelain --untracked-files=no` 为空：已跟踪文件零改动（测试产物仅落在未跟踪的 `.scratch/test_runs/`、`.pytest_cache/` 等区域）。
