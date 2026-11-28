# Task spec

## 背景

在合入 `t094` 与 `t095` 至 `main`（`0264593d`）后进行的完整验证中暴露出一组阻断全量门禁及残余运行风险的缺陷（已于 `p104` 核实登记）：

1. **启动迁移入口自死锁**：`src/mail_core/__main__.py` 的 `run_migrations()` 在 `with check_engine.connect() as conn:` 未退出的情况下，直接调用 `apply_narrow_legacy_conversion` / `upgrade_head_and_verify` / `command.upgrade`。在 `0030`/`0031` 窄转换 `LEGACY` 分支，`verify_narrow_legacy_schema(conn)` 对 `sync_checkpoints` 发起查询使检查连接处于 `idle in transaction` 并持有 `AccessShareLock`；随后 `20261128_0008` 迁移执行 `ALTER TABLE sync_checkpoints ADD COLUMN` 请求 `AccessExclusiveLock`，产生进程内确定性自死锁（导致 `test_t8_real_0030_legacy_shape_upgrades_via_startup` 无论全量还是单跑均必挂，且真实旧库原地启动升级必挂）。
2. **`t094` 遗漏 `test_t092` 边界断言与 DB 级回填测试**：排除死锁用例跑完剩余 711 条后端用例后，暴露 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:294-295` 仍硬编码 `CURRENT_HEAD_REVISION == "20261126_0007"` 导致必败；同时 `0007 -> 20261128_0008` 的存量 `sync_checkpoints.last_delta_settled_at` 回填尚缺带真实数据的数据库级升降/升级测试。
3. **`t095` 遗留三处实现瑕疵**：`patrol.py:249-252` 对已触发账号级短路的后续目录仍执行 `_record_attempt` 写入 `folder_patrol_status`（且 `patrol.py`/`readiness.py` 存在动态 `__import__`）；`loader.py:93-94` 与 `idle_watcher.py:78` 仍保留硬编码并发预算字面量；`liveness.py:17-21`、`readiness.py:130-139` 与 `tests/mail_core/runtime_isolation.py` 对 `/tmp/kkmail-worker-liveness.json` 缺乏隔离与模式边界，测试会在宿主 `/tmp` 残留旧戳并误伤 `/ready`。

## 契约区

### 范围

- 重构 `src/mail_core/__main__.py` 中 `run_migrations()` 的连接生命周期：只读探测、分类与前置校验在独立已关闭的连接块内完成并释放 `check_engine`，确保进入任何写转换或 Alembic `upgrade` 时不再持有未结束的只读检查事务锁；保留 `test_baseline_unit.py` 对 `baseline.read_database_state(conn)` 的委托契约。
- 修复 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py` 的迁移边界断言，改为与 `test_t090_migration_0006.py` 一致的相对头版本判定并覆盖 `0006 <-> 0007 -> head` 往返；补齐真实 PostgreSQL 下 `20261126_0007 -> 20261128_0008` 存量 `sync_checkpoints` 水位回填测试，以及 `run_migrations()` 释放检查连接后写升级的隔离验证。
- 修正 `src/mail_core/sync/patrol.py`：进入 `short_circuited` 的账号后续同轮目录只做跳过，不写 `folder_patrol_status` 也不累加失败计数；冷却恢复探测成功后清除过期 `patrol_cooldown_until`；清除 `patrol.py` 与 `readiness.py` 的动态 `__import__`。
- 收口并发预算残余硬编码：`src/mail_core/config/loader.py` 的 `total_slots`/`background_start_slot` 与 `src/mail_core/sync/idle_watcher.py` 的 `IdleWatcherConfig.quota` 默认值统一派生自 `mail_core.runtime_budget`；补充直接校验生产入口 `load_config({})` 全字段与 `IdleWatcherConfig()` 同源性的单元测试。
- 收口存活戳隔离与模式边界：`src/mail_core/liveness.py` 在未显式配置 `MAIL_CORE_LIVENESS_STAMP` 且设置了 `MAIL_CORE_DATA_DIR` 时将默认戳放在数据目录内；`src/mail_core/readiness.py` 仅在显式设置 `MAIL_CORE_LIVENESS_STAMP` 或嵌入式 Worker 模式（`MAIL_CORE_EMBEDDED_WORKER != "0"`）时读取并校验本地戳；`tests/mail_core/runtime_isolation.py` 为每个测试隔离 `MAIL_CORE_LIVENESS_STAMP` 至临时目录。
- 跑通完整 100% 后端 PostgreSQL 门禁（0 排除、0 失败）及快速/端到端门禁，并同步相关文档。

### 非范围

- 不更改 `20261128_0008` 迁移本身的表结构或升级语义。
- 不修改 `idle_watcher` 的线程架构、不重做容器内存基准或分布式多机特性。
- 不顺手改写无关历史审阅归档文档。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。创建时均为未勾选（`- [ ]`）；实施验证通过后由实施 Agent 就地打勾（`- [x]`）；由 Review Agent 独立复核打勾真实性。技术选型不作为行为 AC。review 判 FAIL 且需修改交付内容时，实施 Agent 撤回全部打勾，修复并重验后重新打勾；reviewer 用 `TICK-VALID` / `TICK-VOID` 逐条判定。

<!-- /规范 -->

- [x] AC-001：启动迁移入口在任何写路径执行升级或窄转换前先结束只读检查事务并释放检查连接，不产生进程内锁冲突；真实 PostgreSQL 下 `0030` 遗留库经启动迁移入口原地升级至 `20261128_0008` 成功且不阻塞（`test_t8_real_0030_legacy_shape_upgrades_via_startup` 独立及全量通过）；同时真实 PostgreSQL 迁移测试覆盖 `20261126_0007 -> 20261128_0008` 升级后存量 `sync_checkpoints.last_delta_settled_at` 精确回填为各自 `updated_at`。
- [x] AC-002：`test_t092_orthogonal_folder_lifecycle.py` 解除对旧版本 `20261126_0007` 的头部相等硬编码，按至少 `20261126_0007` 且仓库头与 `CURRENT_HEAD_REVISION` 一致的方式验证 `0006 <-> 0007 -> head` 迁移往返并在真实 PostgreSQL 通过。
- [x] AC-003：`patrol.py` 对本轮已账号级短路的同账号后续目录仅跳过、不写 `folder_patrol_status` 也不计入失败次数；多目录账号首次传输/认证故障后仅首目录写一次 `folder_patrol_status`、同账号写一次冷却状态，其余目录零探测且零数据库写入；冷却过期后恢复探测成功清理过期冷却键；`patrol.py` 与 `readiness.py` 不存在运行时 `__import__` 调用。
- [x] AC-004：`load_config({})` 返回的 `db_pool_size`、`db_max_overflow`、`total_slots`、`background_start_slot`、`idle_quota` 与 `IdleWatcherConfig()` 默认 `quota` 全部由 `runtime_budget` 单一来源派生（无硬编码分叉），并在生产配置入口单元测试中直接断言。
- [x] AC-005：设置 `MAIL_CORE_DATA_DIR` 且未显式覆盖 `MAIL_CORE_LIVENESS_STAMP` 时，存活戳默认路径隔离至该数据目录；`/ready` 仅在显式配置 `MAIL_CORE_LIVENESS_STAMP` 或嵌入式 Worker 模式启用时校验本地戳，在分布式模式（`MAIL_CORE_EMBEDDED_WORKER=0` 且未配置戳路径）下不受宿主残留 `/tmp/kkmail-worker-liveness.json` 影响；测试运行时隔离 `MAIL_CORE_LIVENESS_STAMP` 至用例临时目录。
- [x] AC-006：完整 100% 后端 PostgreSQL 测试套件（0 排除、0 失败）及 `docs/blueprint/testing.md` 定义的快速与黑盒门禁（模板契约、敏感扫描、OpenAPI 校验、前端单测/`tsc`/`build`、桌面端单测、Playwright E2E）全部实测通过，并完成关联 spec 与文档更新。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试：AC-001/AC-002 通过真实 PostgreSQL 独立库与隔离 schema 迁移测试及启动入口测试验证；AC-003 通过真实 PostgreSQL patrol 集成测试断言 `FolderPatrolStatus` 行数/未更新时间戳及冷却清理；AC-004/AC-005 通过配置/探针单元测试与隔离运行时环境验证；AC-006 通过完整后端 PostgreSQL 套件及快速/E2E 门禁命令验证。

## 上下文区

- 关联 spec：docs/specs/mail_sync_and_storage.md
- 来源：p104（2026-11-28 实测核实并转办；含 `pg_stat_activity`/`pg_locks` 实锤及剩余 711 条后端用例排查结果）

### 有意不测

- 真实生产多容器重启/Linux 容器匿名页压测：沿用 `t095` 边界，不纳入本 bugfix task，本次仅在单测与真实 PG 集成层验证修复行为与全量后端门禁。

### 测试策略

- 先行在测试中稳定复现 `test_t8_real_0030_legacy_shape_upgrades_via_startup` 与 `test_t092_orthogonal_folder_lifecycle`，并新增 `0007 -> 20261128_0008` 带数据回填测试、`patrol` 短路零写盘断言、`load_config({})` / `IdleWatcherConfig()` 预算同源测试与 `liveness` / `readiness` 模式隔离测试（先红后绿）。
- 修改后先跑定向迁移、patrol、health/config/readiness 测试，最终跑通完整 100% 后端 PostgreSQL 套件（`scripts/run-mail-core-tests.sh run`，0 `-k` 排除）及 `test_cmd` / `blackbox_verify`。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无。死锁锁链（`pid 80428` vs `pid 80430`）、`test_t092` 断言及 `t095` 源码位点均已在 2026-11-28 实测核实。

### 风险与回退

- 风险：重构 `run_migrations()` 连接作用域时需确保只读检查失败分支（如 schema drift、未知版本、dry-run/check_only）仍严格不执行写入且保持 `check_engine.dispose()`；`patrol` 跳过写盘后须保证首失败目录仍推进尝试时钟、不引发同账号在冷却过期后只重复探同一失败目录或与 `t061` 既有单目录失败用例冲突；`liveness.py` 路径推导须保持容器未设 `MAIL_CORE_DATA_DIR` 时 API 与 `worker.healthcheck` 仍能指向相同路径。
- 回退：单提交对应 `t096`，异常时可直接 `git revert` 该提交恢复，且不涉及数据库 schema 变更。

### 依赖与约束

- 依赖：基于当前 `main`（含 `t094`、`t095`）立项；因触及数据库启动迁移编排与并发/生命周期状态，`review_level: full`。
- 约束：遵守 `AGENTS.md` 开发铁律与 TDD 原则（`test_t092` 属 `0008` 引入后的过时头部断言，须以与 `test_t090_migration_0006.py` 一致的边界重写并写明理由）；全量后端门禁必须做到 **0 排除单次全绿**。

### Finalization 时更新的 blueprint

- `docs/blueprint/testing.md`：更新全量后端 PostgreSQL 门禁最新验证记录与覆盖说明（如有需要），并确保 `docs/specs/mail_sync_and_storage.md` front matter `tasks` 登记 `t096`。
