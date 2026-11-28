---
tid: "t096"
slug: "startup_migration_deadlock_and_runtime_fixes"
title: "修复启动迁移自死锁及 t094/t095 收敛遗留缺陷"
status: "done"
branch: "t096_startup_migration_deadlock_and_runtime_fixes"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "bac5baebef3a5c1d37c53e3f3f4cdd006f323582"
spec_source_sha: "bac5baebef3a5c1d37c53e3f3f4cdd006f323582"
depends_on: ""
conflicts_with: ""
note: ""
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- **TDD 先红后绿**：新增单元测试 `tests/mail_core/test_t096_fixes_unit.py` 与 PG 集成测试 `tests/mail_core/test_t096_migration_and_patrol.py`，修改生产代码前实测 `4 failed`（unit）与 `7 failed, 1 passed`（unit+PG，其中回填基线测试先通过、锁释放/短路写盘/预算同源/隔离均先红）。
- **`run_migrations()` 自死锁根因修复**：重构 `src/mail_core/__main__.py`，将 `baseline.read_database_state(conn)`、`plan_migration` 与 `verify_for_plan` 全部收敛在独立 `with check_engine.connect() as conn:` + `finally: check_engine.dispose()` 块内，仅在只读检查连接与事务彻底关闭释放后再执行 `check_only` 返回或 `EMPTY_DATABASE`/`UPGRADE_TO_HEAD`/`AT_BASELINE`/`LEGACY` 写路径，消除 `verify_narrow_legacy_schema` 持有 `AccessShareLock` 与 `20261128_0008` `ALTER TABLE sync_checkpoints` 请求 `AccessExclusiveLock` 的进程内自死锁。
- **`test_t092` 过时头部断言重写理由（per TDD 原则）**：`20261128_0008` 成为新 `head` 后，`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:294-297` 原 `CURRENT_HEAD_REVISION == "20261126_0007"` / `get_heads() == ["20261126_0007"]` 语义随新版本推进失效；改为与 `test_t090_migration_0006.py` 一致的 `>= "20261126_0007"`、`get_heads() == [CURRENT_HEAD_REVISION]` 与 `command.upgrade(cfg, "20261126_0007")` 后再测试 `0006 <-> 0007 -> head` 往返。
- **patrol 短路、预算与存活戳收口**：`patrol.py` 短路分支跳过同轮后续目录且不写 `FolderPatrolStatus`、不递增 `result.failed`，在探测成功路径 `_clear_cooldown(account)` 清理过期冷却键，并移除 `patrol.py` 与 `readiness.py` 中全部运行时 `__import__`；`loader.py`（`total_slots`/`background_start_slot`）与 `idle_watcher.py`（`IdleWatcherConfig.quota`）全部改为派生自 `mail_core.runtime_budget`；`liveness.py` 在设 `MAIL_CORE_DATA_DIR` 时隔离默认戳路径并自动创建父目录，`readiness.py` 仅在显式配置 `MAIL_CORE_LIVENESS_STAMP` 或嵌入式模式（`MAIL_CORE_EMBEDDED_WORKER != "0"`）时读取本地戳，`tests/mail_core/runtime_isolation.py` 为每个测试隔离 `MAIL_CORE_LIVENESS_STAMP`。
- **全量与定向实测**：修复后先以单位测试 `59 passed`（0.98s）及定向 PG 集成 `75 passed`（90.28s）确认绿灯，再跑通快速门禁（`.repo_template` contract `389 passed, 1 skipped`、OpenAPI `46 paths` 一致、`src/frontend` vitest/`tsc -b`/`build`/`css:check`/`openapi:check` 全通过、`src/desktop` 测试全通过、`check_doc_sensitive.py` 38 files 0 违规、`check_dep_locks.py --check` 通过、双 compose 校验通过）、`blackbox_verify` E2E（`26 passed`）、**100% 全量 PostgreSQL 后端套件（`scripts/run-mail-core-tests.sh run`，0 排除，`2335 passed, 2 skipped`，总覆盖率 87%）** 以及 `test_t8_real_0030_legacy_shape_upgrades_via_startup` 独立实测（`1 passed` in 2.82s）。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-28T15:36:35+08:00)

`review_code.md` Round 1 零 finding（`verdict: PASS`）；`review_test.md` Round 1 有 3 条非阻断 `minor` finding（`verdict: PASS`），已登记 [`docs/pending/p105_t096_minor_followups.md`](../../pending/p105_t096_minor_followups.md) 跟进：

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t096_test_f001|minor|遗留|巡检短路非阻断深度覆盖（预置行时间戳不变、冷却期跳过、AUTH 与 factory 异常分支），为冻结已审作用域转入 `p105` 跟进|p105|
|t096_test_f002|minor|遗留|存活戳测试补充 `EMBEDDED=0` + 显式戳与 `tmp_path` 父目录断言及夹具清理，非阻断转入 `p105`|p105|
|t096_test_f003|minor|遗留|启动迁移连接销毁探测补充 `LEGACY` 分支、`pg_stat_activity` 归零与漂移/回滚错误分支，非阻断转入 `p105`|p105|

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：单元测试 `KKMAIL_TEST_MODE=unit PYTHONPATH=src .venv/bin/python -m pytest tests/mail_core/test_t096_fixes_unit.py tests/mail_core/test_t095_contract_unit.py tests/mail_core/test_baseline_unit.py tests/mail_core/test_config.py tests/mail_core/test_a104_pool_kwargs.py tests/mail_core/test_a294_healthcheck_env.py -q --no-cov`（59 passed）；独立 0030 回归 `./scripts/run-mail-core-tests.sh run --no-cov -k "test_t8_real_0030_legacy_shape_upgrades_via_startup"`（1 passed in 2.82s）；100% 后端 PostgreSQL 套件 `./scripts/run-mail-core-tests.sh run`（0 排除，2335 passed, 2 skipped in 2124.59s，总覆盖率 87%）；快速门禁 `test_cmd`（`.repo_template` contract 389 passed/1 skipped、前端 vitest/`openapi:check`/`css:check`/`tsc -b`/`build`、桌面端 `npm test`、`check_doc_sensitive.py` 0 违规）、`export_openapi.py --check`（46 paths 一致）、`check_dep_locks.py --check` 与双 Compose 配置校验均通过
- 黑盒：`npm --prefix src/frontend run test:e2e`（Playwright 26 passed in 36.3s）
- review：`review_code.md` Round 1 `PASS`（0 finding，`reviewed_scope: 0d2fd3431fd48ccf`）；`review_test.md` Round 1 `PASS`（0 critical/important，3 minor 均已登记 `p105` 处置，`reviewed_scope: 0d2fd3431fd48ccf`）
- AC 判定：见 `task.md` 行内打勾（AC-001 ~ AC-006 全部 `- [x]`）

### 结果摘要

- 修复 `src/mail_core/__main__.py:run_migrations()` 在未释放只读检查连接前执行写升级/转换导致的 `AccessShareLock` vs `AccessExclusiveLock` 确定性自死锁，解除 `test_t8_real_0030_legacy_shape_upgrades_via_startup` 永久挂起，并新增真实 PG `0007 -> 20261128_0008` `last_delta_settled_at` 回填与连接闭合检查测试。
- 修正 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py` 过时头部断言，完成 `0006 <-> 0007 -> head` 往返与全量 100% 后端 PostgreSQL 测试一次通过。
- 修复 `src/mail_core/sync/patrol.py` 短路目录零写盘与零额外失败计数、恢复探测清理过期冷却键及清理 `patrol.py`/`readiness.py` 动态 `__import__`；将 `loader.py`（`total_slots`/`background_start_slot`）与 `idle_watcher.py`（`IdleWatcherConfig.quota`）全量收敛到 `mail_core.runtime_budget`；隔离 `liveness.py`/`readiness.py`/`tests/mail_core/runtime_isolation.py` 的存活戳路径与分布式模式边界。

### 长期文档闭环

在 active spec 的 front matter `tasks` 清单中登记当前 tid（`task.py specs list --json`）；无长期 spec 变更时写 `- specs_index: not_applicable: 具体原因`。正式 spike 须有 report、现存 finding、采纳结论、后续 tid 或无需后续理由；finish 会检查这些引用。

- specs_index: [`docs/specs/mail_sync_and_storage.md`](../../specs/mail_sync_and_storage.md)（已于 `tasks` front matter 登记 `t096`，并同步 §二第 5 条、§八第 1 条与 `docs/blueprint/testing.md` 门禁矩阵）
- pending: `p104`（已于 `task-create` 阶段经 `pending.py close --resolution transferred --fix-ref t096` 闭环）、`p105`（Round 1 3 条非阻断 `minor` follow-up，status=`todo`）
