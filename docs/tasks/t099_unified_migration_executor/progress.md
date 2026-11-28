---
tid: "t099"
slug: "unified_migration_executor"
title: "统一数据库迁移执行器与连接生命周期"
status: "done"
branch: "t099_unified_migration_executor"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "7746212f8d96870d0b7e75fd1868c159993d1a27"
spec_source_sha: "7746212f8d96870d0b7e75fd1868c159993d1a27"
depends_on: ""
conflicts_with: ""
note: "p105: 启动、离线和只读检查共用事务边界"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 基线：云端 main `7746212f`。验证基线即该提交的 Alembic head（`20261128_0008`）；t097 若新增 revision、t098 若改 `__main__.py`，集成时由主会话复验，本 task 只动迁移入口调用点（`run_migrations` 薄适配）与 `baseline.py` 执行器。
- 实施：`baseline.py` 新增单一执行器 `execute_migration(database_url, *, mode, policy)`——检查段经 `read_only_connection` + `plan_migration` + `verify_for_plan` 产出与连接无关的计划，上下文退出（引擎销毁）后才按计划显式分派写阶段；`MigrationMode`（WRITE/CHECK_ONLY/DRY_RUN）与 `MigrationPolicy`（`STARTUP_POLICY`/`OFFLINE_POLICY`：空库初始化许可、LEGACY 校验失败措辞、转换错误重包装、AT_BASELINE 写动作）承载全部入口差异。`__main__.run_migrations` 与 `baseline.run_migration` 收为薄适配，公开签名不变（`SchemaValidationError` 本为 `RuntimeError` 子类，启动入口的拒绝统一以计划文案抛出）。两处经 Round 1 复审确认的行为 delta 如实登记：（1）离线入口 AT_BASELINE 校验失败文案与启动入口统一，尾部多出「The database was not modified.」一句（启动侧原文案本有此句、未变；该句属实，校验失败发生在任何写入之前）；（2）基线离线流程在检查段内跑的 `stamp_unified_baseline(dry_run=True)` 预检对 0007 类已知较旧 revision 会误拒（盖印目标只接受空表/窄转换 revision），统一后删除该预检，离线入口与启动入口一致地对此类库执行增量升级——与 AC-001 意图一致，属修旧误拒。
- 既有测试处置：`test_baseline_unit.py` 的 A2 源码形状断言（`test_startup_entry_reads_state_via_baseline_helper`）因执行器收编状态读取而失效，整体退役并写明理由，新增覆盖新语义的 `test_startup_entry_delegates_to_shared_executor` 与执行器分派单元测试 6 条；`test_sidecar_detection.py` 的 MULTIPLE fake 按 A2 先例把 patch 点从 `sqlalchemy.create_engine` 改指 `mail_core.db.baseline.create_engine` 并给 FakeConn 补 `rollback()`，断言未动；`test_t096_migration_and_patrol.py` 水位回填夹具中 Sent 目录角色由误写的 `inbox` 改为 `sent`（回填 SQL 与角色无关，断言不变）。
- 验证环境：云端无 Docker，官方 PG 套件守卫（`test_pg_runtime.guard_database`）硬绑 Docker 所有权记录，无法在本机走官方 harness。用仓库 `fetch-pg-binaries.sh` 的固定 SHA-256 便携包自备真实 PostgreSQL 16.6（127.0.0.1:55433），新增 PG 测试以与提交版完全一致的副本在守卫链外实测；`tests/scripts` 套件在仓内直跑。官方 harness 下的后端全量 PG 套件复跑登记 pending（见收尾报告），待 Mac 集成时执行。
- 验证结果（真实 PG 16.6）：新增 `test_t099_migration_executor.py` 7 条全过（AC-001~AC-004）；回归 `test_startup_migrations.py` 13 条、`test_migration_validation.py`、`test_legacy_migration.py`、`tests/scripts/test_migrate_to_unified_baseline.py` 35 条、`test_t096` AC-001 两条全过。unit 全量（KKMAIL_TEST_MODE=unit）：2041 passed / 1 failed / 84 skipped，唯一失败 `test_t092_downstream_isolation_and_api.py::test_ac003_mixed_startup_and_patrol` 在未改动基线 `7746212f` 同环境同法复跑亦失败（单文件两边均 skip，属套件顺序污染），与本 task 无关。模板契约 359 passed / 30 failed，基线同环境同为 30 failed（云端环境问题，非本 task 引入）；`check_doc_sensitive` 0 违规、`check_dep_locks --check` 通过。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-29T00:42:52+08:00)

review_code overall=PASS、review_test overall=PASS；AC-001~AC-004 全部 TICK-VALID（reviewer 独立复跑并对 AC-002 做双向变异复证）。4 条 finding 均为 minor，全部已修。

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t099_code_f001|minor|已修|离线 AT_BASELINE 校验失败文案与启动统一后多出尾句，progress 原「文案不变」表述不准确；已在实施笔记如实登记该 delta|docs/tasks/t099_unified_migration_executor/progress.md 实施笔记|
|t099_code_f002|minor|已修|基线离线检查段的盖印预检会误拒 0007 类已知较旧 revision，执行器删除后与启动一致升级；属修旧误拒，已在实施笔记登记|src/mail_core/db/baseline.py execute_migration；progress.md 实施笔记|
|t099_code_f003|minor|已修|写分派 LEGACY 原为消去法落入，已改为显式 action 分支并加未分派 action 的 AssertionError 兜底|src/mail_core/db/baseline.py execute_migration|
|t099_test_f001|minor|已修|AC-003/004 快照 schema 维度原仅表名集合，已补每表列名+类型指纹，复跑全过|tests/mail_core/test_t099_migration_executor.py \_snapshot|

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足（AC-001~AC-004 全部打勾且经复审 TICK-VALID）
- 测试：真实 PostgreSQL 16.6（自备便携实例）——新增 t099 套件 7 条全过；回归 test_startup_migrations 13 条、test_migration_validation、test_legacy_migration、tests/scripts 离线套件 35 条、test_t096 AC-001 两条全过；unit 全量 2041 passed / 1 failed（失败为基线同环境亦失败的既存顺序污染，与本 task 无关）/ 84 skipped；check_doc_sensitive 0 违规、check_dep_locks 通过。官方 harness 后端全量 PG 套件因云端无 Docker 未执行，见 p109。
- 黑盒：不适用（本 task 为迁移执行器内部统一，无 UI/外部行为面；入口行为由 PG 集成测试覆盖）
- review：Round 1 review_code PASS、review_test PASS，4 条 minor 全部已修（见 Review 处置）
- AC 判定：见 `task.md` 行内打勾

### 结果摘要

- 统一执行器 `baseline.execute_migration` 收编全部迁移入口的检查、只读连接释放与写分派；入口差异收敛为 `MigrationPolicy` 四项。遗留：p109（官方 harness 全量 PG 复跑，待 Mac 集成）。

### 长期文档闭环

- specs_index: docs/specs/mail_sync_and_storage.md 的 tasks 清单已登记 t099；blueprint architecture.md 已记录统一迁移执行边界与入口策略、testing.md 已登记检查连接释放与存量库完整回滚验证。
