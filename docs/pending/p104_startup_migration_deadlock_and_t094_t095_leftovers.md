---
pid: "p104"
slug: "startup_migration_deadlock_and_t094_t095_leftovers"
status: "todo"
---
# p104 启动迁移自死锁、0007过期测试及t095预算巡检探针遗留缺陷

- 现象：
    - 完整后端 PostgreSQL 测试套件于 `tests/mail_core/test_startup_migrations.py::test_t8_real_0030_legacy_shape_upgrades_via_startup`（约 69%）确定性永久挂死，且单独执行该 1 条用例同样在 25s 内超时卡死；`pg_stat_activity` 与 `pg_locks` 实测同一进程内检查连接 `idle in transaction` 阻塞 `ALTER TABLE sync_checkpoints ADD COLUMN last_delta_settled_at TIMESTAMP WITH TIME ZONE`。
    - 排除上述死锁用例跑完剩余 711 条后端用例（8m55s），`710 passed, 1 failed`：`tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:294` 报 `AssertionError: assert '20261128_0008' == '20261126_0007'`。
    - 审计 `t095` 已合入代码发现 3 处实现瑕疵：`patrol.py:249-252` 短路账号后续目录仍写盘；`loader.py:93-94` 与 `idle_watcher.py:78` 仍有硬编码并发预算字面量；`liveness.py:17-21` 与 `readiness.py:130-139` 在 `/tmp` 默认路径存在无隔离污染（本地已观测到测试留下的 `/tmp/kkmail-worker-liveness.json`）。
- 影响：
    - **产品缺陷**：任何 `20261031_0030` / `20261107_0031` 旧库经 `python -m mail_core` 启动原地升级至 `20261128_0008`（或更广义地，`run_migrations()` 任一写入分支在只读检查事务未关闭时修改表结构）都会在启动阶段永久锁死；全量后端门禁无法跑通。
    - **同轮连带/已确认位点并集**：
        1. `src/mail_core/__main__.py:57-130`（`run_migrations` 全写分支未先退出 `check_engine.connect()` 事务与释放引擎；已对比离线 `src/mail_core/db/baseline.py:1170-1226` `run_migration()` 已先退出 `with read_only_connection`）；
        2. `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:294-297`（硬编码 `0007` 头部版本；已全仓 `rg` `tests/`，其余 `test_t090` / `test_sync_execution_unit` / `test_outbox_retention_unit` / `test_migration_validation` 均已对比 `CURRENT_HEAD_REVISION`）；
        3. `src/mail_core/sync/patrol.py:249-252`（已短路账号后续目录仍调用 `_record_attempt` 写 `folder_patrol_status` 并在 `patrol.py:67,282` / `readiness.py:106` 使用动态 `__import__`）；
        4. `src/mail_core/config/loader.py:93-94`（`total_slots=8` / `background_start_slot=2` 硬编码）与 `src/mail_core/sync/idle_watcher.py:78`（`IdleWatcherConfig.quota=32` 硬编码）；
        5. `src/mail_core/liveness.py:17-21`、`src/mail_core/readiness.py:130-139`、`tests/mail_core/runtime_isolation.py:104-106`（默认 `/tmp` 戳路径未按 `MAIL_CORE_DATA_DIR` / 测试沙箱隔离，且非嵌入式模式或残留戳会误伤 `/ready`）。
- 根因：
    - **可验证机制与分类**：
        1. `run_migrations()`（产品缺陷）把 `apply_narrow_legacy_conversion`、`upgrade_head_and_verify` 与 `command.upgrade` 嵌套在 `with check_engine.connect() as conn:` 内；`verify_narrow_legacy_schema(conn)` 对 `sync_checkpoints` 发起 `SELECT count(*)` 获取 `AccessShareLock` 后，`conn` 直到整次升级返回才关闭，`upgrade_head_and_verify` 的 `20261128_0008` 迁移首次 `ALTER TABLE sync_checkpoints` 请求 `AccessExclusiveLock`，产生进程内自死锁。
        2. `t094` 仅跑局部 `-k` 门禁且全量止步于 69%，遗漏了 85% 处的 `test_t092` 边界测试（测试漏更新）与 `0007 -> 0008` 存量回填 DB 级实测。
        3. `t095` 短路分支误复用了单目录失败写盘路径；`loader.py` / `IdleWatcherConfig` 漏改两处默认字面量；`liveness` / `readiness` 与 `runtime_isolation.py` 缺少目录与运行模式边界隔离。
- 测试缺口：
    - `test_t8_real_0030_legacy_shape_upgrades_via_startup` 在 `t094` 未单独覆盖；缺少 `20261126_0007 -> 20261128_0008` 真实带数据回填校验（仅源码守卫）。
    - `test_t095_patrol_readiness.py` 未断言被短路目录零 `FolderPatrolStatus` 写入；`test_t095_contract_unit.py` 只测 `MailCoreConfig()` dataclass，未测 `load_config({})` 全字段同源与 `IdleWatcherConfig()`；缺少 `/tmp` 残留戳对分布式/无戳模式 `/ready` 影响的验证。
- 线索：
    - 2026-11-28 实测 `pg_stat_activity`：`pid 80428 (idle in transaction)` `SELECT attr.conrelid...` 阻塞 `pid 80430` `ALTER TABLE sync_checkpoints ADD COLUMN last_delta_settled_at`（`pg_locks` `AccessExclusiveLock granted=f, blockers={80428}`）；单独执行 `scripts/run-mail-core-tests.sh run -k test_t8_real_0030_legacy_shape_upgrades_via_startup --no-cov -vv` 25s 超时挂死；剩余 711 条 PG 用例 710 passed / 1 failed。
- 处理：未开
