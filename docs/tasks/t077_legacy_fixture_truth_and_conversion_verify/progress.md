---
tid: "t077"
slug: "legacy_fixture_truth_and_conversion_verify"
title: "LEGACY 夹具忠实重放历史 DDL 并去除迁移校验豁免补丁"
status: "done"
branch: "t077_legacy_fixture_truth_and_conversion_verify"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "bc61fd8bcf40e82819f9769f0ef7467e562c7c5f"
spec_source_sha: "e3e45afeb8bd82af83073ffdef14da90aad2ea4e"
depends_on: "t076"
conflicts_with: ""
note: "来源 p076（t076 R3/R4 遗留）；按开发铁律从根因修正：夹具由当前 head 反推伪造旧库导致假绿，f006 豁免补丁属临时妥协"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 根因修正（拒绝妥协）：删除 t076 f006 引入的 `ignore_account_column_drift` / `_is_account_column_drift` / `_ACCOUNT_HEALTH_COLUMNS` 整个豁免补丁；`verify_baseline_schema` 恢复为无豁免的全量比对。
- 校验归位（架构至上）：`apply_narrow_legacy_conversion` 事务内不再用当前 head ORM 比对升级输入；新增 `upgrade_head_and_verify` 作为两个迁移入口的单一收敛点（先 `command.upgrade(head)`，再对升级后库做 `verify_baseline_schema`）。`__main__.run_migrations` 的 UPGRADE_TO_HEAD / LEGACY 分支补 `_raise_if_schema_drift`；`baseline.run_migration` 的 UPGRADE_TO_HEAD 分支由「离线拒绝」改为同样重放增量 revision 并校验，两入口行为统一。
- 夹具忠实化（零兼容）：`_make_0030_db` / `_pg_build_0030_shape` / `_create_0030_schema` 改由 `upgrade(cfg, "20261107_0001")` 派生真实历史形状，各自在构造后立即断言 `accounts` 含 `sync_status`、不含三列（防退化护栏）。
- TDD 合规：`test_conversion_rejects_drifted_legacy_schema_and_rolls_back` 与 `test_migrate_from_0030_legacy_database_success` 因「转换事务内零写入」语义变更而整体重写并写明理由，未就地改预期；新增 `test_real_0030_shape_upgrades_to_head_with_forward_data_mapping`（离线入口）与 `test_t8_real_0030_legacy_shape_upgrades_via_startup`（启动入口）覆盖真实形状正向升级 + 历史 `sync_status` 值映射。编排类用例的 `_mock_upgrade` 仅 stub 协作方 `verify_upgraded_schema`，真实校验由上述 PG 用例承担。
- 闭环：`p076` 由本 task 闭环（resolved / fix_ref=t077）；`docs/specs/mail_sync_and_storage.md` front matter 登记 `t077`。
- 既存门禁失败：`test_check_dep_locks`（uv lock 漂移）与 `test_check_doc_sensitive::test_repo_docs_gate_passes`（14 处，均为采纳前既有：13 处历史 review 文档占位符/示例误判 + 1 处 t076 交付里的示例邮箱字符串），主仓/t076 HEAD 复现，非本 task 引入；按配置缺陷报告约定未静默绕过、未改无关文件。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-12T11:20:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t077_code_f001|minor|已修|同步 baseline 模块 / verify_narrow_legacy_schema / plan_migration 的 docstring 为新升级时序|src/mail_core/db/baseline.py|
|t077_code_f002|minor|已修|同步 testing.md 迁移校验约定与单 head 线性链描述，并修正 task.md Finalization 指向|docs/blueprint/testing.md|
|t077_code_f003|minor|已修|启动入口删除 \_raise_if_schema_drift，UPGRADE_TO_HEAD / LEGACY 统一复用 upgrade_head_and_verify|src/mail_core/__main__.py|
|t077_code_f004|minor|已修|verify_upgraded_schema 改用 read_only_connection（只读事务 + statement_timeout）|src/mail_core/db/baseline.py|
|t077_test_f001|minor|已修|新增 0001 形状 catalog 的四列差异负向护栏，防止豁免逻辑复活|tests/scripts/test_migrate_to_unified_baseline.py|
|t077_test_f002|minor|已修|新增 offline UPGRADE_TO_HEAD 正向用例（重放 0002 + 全量校验）|tests/scripts/test_migrate_to_unified_baseline.py|
|t077_test_f003|minor|已修|同步 test_startup_migrations / test_migration_validation 模块 docstring 为真实历史 DDL 夹具|tests/mail_core/test_startup_migrations.py|

Round 1 两轴 PASS、7 条 minor 全部已修；按「review 后改交付内容必须重新 review」进入 Round 2。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：定向 PG 80 passed（迁移正向/逆向、真实 0030 形状启动与离线双入口升级、历史值映射、负向 drift、豁免护栏、夹具形状自检、离线 UPGRADE_TO_HEAD）；后端 unit 1654 passed（2 个采纳前基线既存失败：`test_check_dep_locks` uv lock 漂移、`test_check_doc_sensitive` 历史 review 文档占位符/示例误判，主仓/t076 HEAD 复现）；前端/契约未改动无需重跑；全量 PG 门禁 **2189 passed、2 skipped、2 个上述既存失败**，无本 task 引入失败（前三次因测试 PG 瞬时 recovery mode / statement timeout / connection timeout 中断，均为基础设施故障而非代码失败；重启专用测试服务后第 4 次跑通，见 `.scratch/pg_gate_t077_clean.log`）。
- 黑盒：stubApi E2E 21 passed；全栈真实 FastAPI + PG + Worker + 生产 SPA Playwright 8 passed（真实重放 0001→0002 迁移链）。
- review：full 级 2 轮，`review_code.md` / `review_test.md` Round 2 均 PASS；Round 1 七条 minor 全部已修并复核，Round 2 零 finding，coverage 6/6，无 TICK-VOID。
- AC 判定：见 `task.md` 行内打勾（AC-001~AC-006 全部 TICK-VALID）

### 结果摘要

- 从根因修正 p076：删除 f006 豁免补丁（`ignore_account_column_drift` / `_is_account_column_drift` / `_ACCOUNT_HEALTH_COLUMNS`）；三个 LEGACY 夹具改由 `upgrade(cfg,"20261107_0001")` 忠实派生真实历史形状并加形状护栏；全量 `verify_baseline_schema` 归位到 `upgrade head` 之后，两入口统一收敛到 `upgrade_head_and_verify`；离线入口不再拒绝落后 revision；负向 drift 用例与 0030 成功用例按 TDD 整体重写并写明理由；新增启动/离线双入口真实正向用例与豁免负向护栏。来源 `p076` 已闭环（resolved / fix_ref=t077），本 task 无新增遗留。

### 长期文档闭环

- specs_index：`docs/specs/mail_sync_and_storage.md` front matter `tasks` 已登记 `t077`。
- blueprint：`docs/blueprint/testing.md` 迁移校验约定已改为「升级到 head 后全量比对、无任何列豁免」并同步单 head 线性链描述。
- 正式 spike：无（本 task 无未核实外部契约）。
