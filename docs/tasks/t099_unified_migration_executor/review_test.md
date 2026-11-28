# Task review t099（reviewer_focus: 测试）

- task：`t099_unified_migration_executor`
- spec：`docs/tasks/t099_unified_migration_executor/task.md`
- diff_anchor：`7746212f8d96870d0b7e75fd1868c159993d1a27`
- target：`git diff 7746212f8d96870d0b7e75fd1868c159993d1a27..e653b16f`
- round：2
- reviewed_at：2026-11-29T00:48:09+08:00

reviewed_scope: 53a4393166336e35

## Findings

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t099_test_f001|minor|遗留|AC-003/AC-004 的 `_snapshot` 中「schema」维度只是表名集合（`_snapshot` 的 `tables`），不含列/类型/约束；漂移与回滚的列级证据实际由 AC-003 夹具的畸形 `folder_patrol_status` 被检出（verify_narrow 列级校验）与 AC-004 的 patrol 表存在性＋cursor 数据承担，本 task 场景下足够，但快照本身不足以发现「列被改型但表名不变」类回滚残缺。建议后续给 `_snapshot` 补 information_schema 列指纹。|tests/mail_core/test_t099_migration_executor.py `_snapshot`|

## 复跑环境与结果（reviewer 独立复跑）

- 环境：本机复审时 55433 端口无 PG 在跑、`/tmp/t099tree` 已不存在，reviewer 以仓库 `.pg-runtime` 便携包自备真实 PostgreSQL（16.2，与实施侧 16.6 同为 16 大版本线）在 127.0.0.1:55433 重建，并按实施侧跑法重建 `/tmp/t099tree`（src/scripts/docs 符号链接指向 worktree、tests/mail_core/conftest.py 为去掉 Docker 所有权守卫的替代版，另保留原 conftest 的环境快照 autouse 夹具——缺它时合跑出现套件间环境污染假失败，单跑均过，已定位为复跑脚手架问题而非实现问题）。官方 harness 全量复跑仍归 p109，待 Mac 集成执行。
- `tests/mail_core/test_t099_migration_executor.py`：**7 passed**。
- 回归：`test_startup_migrations.py` + `test_migration_validation.py` + `test_legacy_migration.py` 合跑 **28 passed**；`tests/scripts/test_migrate_to_unified_baseline.py` 在 worktree 直跑 **35 passed**；`test_t096_migration_and_patrol.py -k ac001` **2 passed**（含水位回填条，见下 Sent 角色）。
- unit：worktree 内 `KKMAIL_TEST_MODE=unit` 跑 `test_baseline_unit.py` + `test_sidecar_detection.py`：**60 passed**（含新执行器单元 6 条与改造后的 A2 测试、MULTIPLE fake 测试）。

## AC 逐条判定

### AC-001：TICK-VALID（re_verified）

- 空库初始化：`test_ac001_migrate_only_initializes_empty_database` 经真实 CLI `main(["--migrate-only"])` 在专用空库上断言 revision == CURRENT_HEAD_REVISION 且 REQUIRED_TABLES 全 present；`test_ac002_check_connection_released_before_empty_upgrade` 另证普通启动 `run_migrations()` 空库到 head。离线拒绝空库：scripts 套件 `test_run_migration_rejects_empty_database` 通过（35 条内）。
- 受支持旧库实际写路径升级：`test_ac001_offline_tool_upgrades_supported_legacy_to_head` 用 0030 夹具（由历史 0001 基线派生、DROP folder_patrol_status、盖 0030、含 account/folder/checkpoint 业务行）调 `baseline.run_migration(db_url)` 真实写路径，断言到 head、patrol 行生成且 `verify_upgraded_schema(db_url) == []`（完整 compare_metadata 校验，非空转）。
- 已知较旧 revision 增量升级：t099 文件内由 LEGACY 路径覆盖；UPGRADE_TO_HEAD 写路径由回归套件覆盖且复跑通过——`test_startup_migrations.py::test_t7_older_baseline_upgrades_in_place_with_data_mapping`（启动）与 scripts 套件 `test_offline_upgrade_to_head_from_0001_baseline`（离线）。

### AC-002：TICK-VALID（re_verified，含变异验证）

- 观测方法核查：`_record_check_pids` 以 monkeypatch spy 包裹生产函数 `baseline.read_database_state`，在其真实调用时于检查连接上执行 `SELECT pg_backend_pid()` 捕获 backend PID——执行器检查段只用一条只读连接（状态读取与 `verify_for_plan` 同连接），故该 PID 即「参与该次只读检查」的连接。断言点在首个写入口内部：空库路径 spy `alembic.command.upgrade`、LEGACY 路径 spy `baseline.apply_narrow_legacy_conversion`，进入写函数先断言后才放行真实写操作，时机正确（写连接打开之前/之时）。
- 观测独立性：`_assert_pids_gone` 另建 NullPool 引擎连 admin 库 `postgres`，查 `pg_stat_activity WHERE datname=:db AND pid=ANY(:pids)`，与被测连接、与目标库连接均独立；断言对象是「PID 不再存在于 pg_stat_activity」即物理 backend 已退出，强于「事务结束/idle」观测，符合 AC「物理连接均已关闭」。
- 非空转证据（reviewer 变异实验，/tmp 副本，未动 worktree）：①直接以一条存活连接的 PID 调 `_assert_pids_gone` → 如期 AssertionError（10s 轮询耗尽），以不存在 PID 调 → 通过，证明断言对存活/消亡双向敏感；②把 `read_only_connection` 的 `engine.dispose()` 删去（变异副本）后重跑，两条 AC-002 测试**双双 FAILED**（各耗满 10s 轮询），证明测试确实能抓到「连接未释放」。轮询上限 10s 是对 backend 退出时延的容忍，不构成假绿：变异下 PID 始终存在、必然超时失败。
- LEGACY 转换后真实升级完成：同测试断言转换后 revision 到 head、patrol 数据（last_status JSON、failures=3）正确迁移、cursor 仅余 `delta_token`。

### AC-003：TICK-VALID（re_verified）

- 只检查不写：`test_ac003_check_only_on_upgradeable_database_writes_nothing` 在 0001 库（含业务行）上先后跑真实 `--check-migrations`（`main()` 入口）与离线 `run_migration(dry_run=True)`，前后 `_snapshot` 全等（schema 表集/版本/patrol/cursor/accounts，见 f001 的维度说明）。
- 漂移双入口拒绝：`test_ac003_drifted_supported_legacy_refused_by_all_entries` 给 0030 库加畸形 `folder_patrol_status`（仅 VARCHAR folder_id），启动、启动 check_only 均以 RuntimeError「not supported」拒绝，离线 write 与 dry-run 均以 SchemaValidationError「missing required columns」拒绝，四次调用后快照逐次全等。启动侧 `pytest.raises(RuntimeError)` 与 SchemaValidationError 的子类关系不构成假绿：启动 LEGACY 校验失败在新旧实现中均以含「not supported」的文案抛出，且离线侧单独以 SchemaValidationError 类型＋detail 文案断言。

### AC-004：TICK-VALID（re_verified）

- 注入点确在部分写入之后：monkeypatch 的是 `baseline.migrate_patrol_status_data`，包装器先调真实函数（patrol 行 INSERT＋sync_checkpoints cursor 键剥离的 UPDATE 均已执行），且其在 `apply_narrow_legacy_conversion` 内的调用顺序位于 `ensure_folder_patrol_status_table`（建表 DDL）之后、`stamp_unified_baseline` 之前，随后才 raise SchemaValidationError——即 DDL＋DML 部分写入后、在同一写事务内触发。patch 点是生产转换函数按模块全局名解析的真实引用，触达生产逻辑（复跑时转换确实执行并回滚，非旁路）。
- 回滚完整性：失败后快照与调用前全等，且单独断言 `folder_patrol_status not in tables`（DDL 回滚）、cursor 恢复含 legacy 键（DML 回滚）、revision 仍为 0030（未盖印）；异常为启动入口重包装的 RuntimeError「rolled back」且 `__cause__` 是 SchemaValidationError。
- 升级未启动的证据：`alembic.command.upgrade` 被计数 spy 替换，失败后 `upgrade_calls == []`——转换失败发生在升级调用前且执行器未继续分派，非事后状态推断。
- 重试与幂等：`monkeypatch.undo()` 撤除注入后重跑成功到 head、patrol 1 行；再对已转换库重跑 `run_migrations()`，快照与成功后全等。

## 既有测试处置核查

- **A2 源码断言退役（test_baseline_unit.py）**：正当。旧 `test_startup_entry_reads_state_via_baseline_helper` 断言 `run_migrations` 源码含 `baseline.read_database_state(conn)`；该调用真实迁入 `execute_migration`，旧形状不复存在。新测试 docstring 写明退役理由，断言改为委托 `execute_migration`＋无 create_engine＋无裸 SQL；且新语义另有行为级覆盖（执行器单元 6 条以真实 `plan_migration` 分类＋事件序断言「check_closed 先于写分派」，PG 7 条端到端）。符合 AGENTS.md「整体删除＋写明理由＋新增覆盖新语义」，非就地改预期。
- **test_sidecar_detection.py fake 处置**：正当。仅 patch 点随实现作用域迁移（`sqlalchemy.create_engine` → `mail_core.db.baseline.create_engine`，注释写明原因）并给 FakeConn 补只读管理器必调的 `rollback()`；拒绝断言（多版本行 → 拒绝）未动，unit 复跑通过。
- **Sent 角色修正**：属实且为契约范围内指定修正。`test_t096_migration_and_patrol.py` 水位回填夹具把 INBOX/Sent 两行拆开参数化，Sent 行 role 由误写的 `inbox` 改为 `sent`（INBOX 保持 `inbox`）；0008 回填 SQL 按 checkpoint 的 updated_at 回填、与 folders.role 无关，测试断言未动；该测试在真实 PG 复跑通过（t096 -k ac001 2 passed 之一）。夹具语义与真实目录角色一致，不再以错误夹具掩盖潜在按 role 过滤的回归。

## AC 复验方式

- AC-001：TICK-VALID，re_verified。独立复跑 `test_ac001_migrate_only_initializes_empty_database`（真实 CLI 空库到 head）、`test_ac001_offline_tool_upgrades_supported_legacy_to_head`（离线真实写路径升级 0030 到 head 且 `verify_upgraded_schema == []`）、scripts 套件 `test_run_migration_rejects_empty_database` 与回归 `test_t7_older_baseline_upgrades_in_place_with_data_mapping` / `test_offline_upgrade_to_head_from_0001_baseline`（较旧 revision 增量升级），全部通过。
- AC-002：TICK-VALID，re_verified。独立复跑两条 AC-002 测试（检查 PID 在检查连接上以 `pg_backend_pid()` 捕获、首个写入口内以独立 admin 连接查 `pg_stat_activity` 断言 PID 不存在），并做双向变异复证：存活 PID 调断言如期失败；删去 `read_only_connection` 的 `engine.dispose()` 后两条测试双双变红。
- AC-003：TICK-VALID，re_verified。独立复跑 `test_ac003_check_only_on_upgradeable_database_writes_nothing`（--check-migrations 与离线 dry-run 前后快照全等）与 `test_ac003_drifted_supported_legacy_refused_by_all_entries`（漂移库被启动、启动检查、离线 write/dry-run 四路拒绝且快照不变），全部通过。
- AC-004：TICK-VALID，re_verified。独立复跑 `test_ac004_conversion_validation_error_rolls_back_fully`：注入点在 patrol 建表与数据迁移真实写入之后，失败后快照与调用前全等、`folder_patrol_status` 不存在、`alembic.command.upgrade` 计数为 0（升级未启动），撤除注入重试成功、已转换库重跑快照一致。

## 结论

- 本轮新发现：1 条 minor（f001 快照 schema 维度仅表名集）；无 critical / important。
- AC-001、AC-002、AC-003、AC-004 打勾全部属实：**TICK-VALID ×4**，均有真实 PostgreSQL 测试触达生产逻辑、断言非空转（AC-002 经双向变异实验复证）。
- 总体判断：PASS。

coverage = 4 / 4

verdict: PASS

## Round 2 复核（2026-11-29T00:48:09+08:00，对象 c39baa66）

reviewed_scope: 53a4393166336e35

复核范围：仅 Round 1 的 4 条 minor finding 的修复属实性与回归（`git diff e653b16f..c39baa66`），不重审其余部分。

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t099_test_f001|minor|已修属实|`_snapshot` 已补每表列名+类型指纹：新增 `columns = {table: sorted((col["name"], str(col["type"])) for col in insp.get_columns(table)) for table in tables}` 并写入返回 dict 的 `"columns"` 键；快照相等比较自此覆盖列名与类型，「列被改型但表名不变」类残缺可被 AC-003/004 的前后快照全等断言发现。实现与 progress.md Review 处置表记载一致。复跑：本机 127.0.0.1:55433 真实 PostgreSQL 在跑，经 `/tmp/t099tree` 副本（符号链接指向 worktree 当前测试文件）＋`MAIL_CORE_DATABASE_URL` 复跑 `test_t099_migration_executor.py`：7 passed，快照增强未引入回归。|tests/mail_core/test_t099_migration_executor.py `_snapshot`|

- t099_code_f001 / f002 / f003（代码侧 finding）：逐条核对见 review_code.md Round 2，结论均为已修属实；其中 f003 附带复跑 `test_baseline_unit.py` 26 passed。
- 本轮新 finding：无。
- 本轮 overall：PASS。测试侧 minor 修复属实，t099 PG 套件 7 条复跑全过、无回归；AC 判定维持 Round 1 结论。

## AC 复验方式

- AC-001：TICK-VALID，re_verified。
- AC-002：TICK-VALID，re_verified。
- AC-003：TICK-VALID，re_verified。
- AC-004：TICK-VALID，re_verified。

（维持 Round 1 判定依据：本轮 diff 仅增强 `_snapshot` 的 schema 指纹维度，使 AC-003/004 的快照全等断言更严，未改任何断言预期或生产路径；增强后套件复跑 7 passed。）

coverage = 4 / 4

verdict: PASS
