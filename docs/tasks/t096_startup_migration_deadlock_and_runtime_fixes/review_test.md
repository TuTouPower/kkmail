# Task review t096（reviewer_focus: 测试）

- task：`t096_startup_migration_deadlock_and_runtime_fixes`
- spec：`docs/tasks/t096_startup_migration_deadlock_and_runtime_fixes/task.md`
- diff_anchor：`bac5baebef3a5c1d37c53e3f3f4cdd006f323582`
- target：`git diff bac5baebef3a5c1d37c53e3f3f4cdd006f323582`
- round：1
- reviewed_at：2026-11-28T15:35:37+08:00

reviewed_scope: 0d2fd3431fd48ccf

## Findings

### t096_test_f001 - `test_ac003_patrol_short_circuit_zero_patrol_writes_and_clears_cooldown_on_recovery` 未覆盖认证故障短路与存量 `FolderPatrolStatus` 行未修改场景

- 严重度：minor
- 锚点：AC-003 覆盖深度可扩充（「首次传输/认证故障后仅首目录写一次 `folder_patrol_status`、同账号写一次冷却状态，其余目录零探测且零数据库写入」）
- 位置：`tests/mail_core/test_t096_migration_and_patrol.py:150-228`（对应生产代码 `src/mail_core/sync/patrol.py:172-174,255-265,270-279,295-296`）
- 问题：该集成测试用 `ConnectionError`（`FailureDomain.TRANSPORT`）对零基线新目录验证了首夹失败后 `len(failing.probed) == 1`、`res.failed == 1`、`len(fps_rows) == 1` 及冷却过期恢复清理，但：（1）未在 `schedule_folder_status_patrol` 中覆盖 `FailureDomain.AUTH` 认证故障或 `provider_factory` 抛异常的短路路径，全量覆盖率显示 `src/mail_core/sync/patrol.py:257,270-279` 未被执行；（2）3 个同账号目录初始均无 `FolderPatrolStatus` 行，`len(fps_rows) == 1` 仅证明未新增行，若后续回归导致已存在 `FolderPatrolStatus` 行的同账号兄弟目录被刷新 `last_probe_at` 或累加 `last_probe_failures`，当前断言无法捕获；同时测试直接跳到冷却过期后，未顺带断言冷却期内复扫命中 `skipped_not_due`（`patrol.py:172-174`）。
- 建议：在 `tests/mail_core/test_t096_migration_and_patrol.py` 增补存在预置 `FolderPatrolStatus` 行时的兄弟目录时间戳/失败数不变断言、`now + 60s` 冷却期跳过断言，以及 `PermanentAuthError`（`FailureDomain.AUTH`）场景以同时验证 `credential_state == "invalid"` 与兄弟目录零写盘。

### t096_test_f002 - `test_ac005` 就绪探测测试未覆盖分布式显式指定戳路径且隔离测试未断言落点位于 `tmp_path`

- 严重度：minor
- 锚点：AC-005 边界组合可更完整（「`/ready` 仅在显式配置 `MAIL_CORE_LIVENESS_STAMP` 或嵌入式 Worker 模式启用时校验本地戳」及「测试运行时隔离 `MAIL_CORE_LIVENESS_STAMP` 至用例临时目录」）
- 位置：`tests/mail_core/test_t096_fixes_unit.py:97-116` 与 `tests/mail_core/test_t096_migration_and_patrol.py:231-238`
- 问题：`test_ac005_distributed_readiness_ignores_stray_default_tmp_stamp` 验证了 `MAIL_CORE_EMBEDDED_WORKER=0`（未设戳变量）忽略残留默认戳、以及 `MAIL_CORE_EMBEDDED_WORKER=1` 校验陈旧默认戳，但未覆盖 `MAIL_CORE_EMBEDDED_WORKER=0` 且显式设置 `MAIL_CORE_LIVENESS_STAMP`（侧车/共享卷显式戳场景，对应 `src/mail_core/readiness.py:133-136` 布尔或左侧分支）仍应校验陈旧戳的用例；此外 `test_ac005_isolated_runtime_does_not_touch_shared_tmp_liveness(tmp_path)` 未使用参数 `tmp_path`，仅断言 `env_val != DEFAULT_STAMP_PATH`，未断言 `Path(env_val).parent == tmp_path` 且未实际写入后确认 `DEFAULT_STAMP_PATH` 不受影响。
- 建议：在 `test_ac005_distributed_readiness_ignores_stray_default_tmp_stamp` 补充 `MAIL_CORE_EMBEDDED_WORKER="0"` + 显式设置陈旧 `MAIL_CORE_LIVENESS_STAMP` 令 `read_worker_active_via_core` 返回 `active is False` 的断言；在 `test_ac005_isolated_runtime_does_not_touch_shared_tmp_liveness` 中校验 `Path(env_val).parent == tmp_path`（并将该纯隔离契约移出整文件 PG `pytestmark` 或保留于单元测试集）。

### t096_test_f003 - `test_ac001_run_migrations_closes_check_connection_before_upgrade` 仅探查空库路径事务数，未直接校验 `LEGACY` 写前释放与检查连接池销毁

- 严重度：minor
- 锚点：AC-001 回归防护可进一步收紧（「在任何写路径执行升级或窄转换前先结束只读检查事务并释放检查连接」）
- 位置：`tests/mail_core/test_t096_migration_and_patrol.py:44-77`（对应生产代码 `src/mail_core/__main__.py:72-102,123-132`）
- 问题：`test_ac001_run_migrations_closes_check_connection_before_upgrade` 以空库触发 `EMPTY_DATABASE` 路径，在 `alembic.command.upgrade` 入口查询 `pg_stat_activity` 的 `state = 'idle in transaction'` 计数为 `0`（修复前实测为 `1`）；虽然真实 `0030` 窄转换升级已由 `test_t8_real_0030_legacy_shape_upgrades_via_startup` 端到端实测通过，但该探针测试未同时覆盖 `LEGACY`（进入 `apply_narrow_legacy_conversion` 前）与总连接数归零（验证 `check_engine.dispose()` 关闭物理检查连接而不仅是事务回滚）。另据全量覆盖率数据，`src/mail_core/__main__.py:89,126`（`LEGACY` 校验拒绝与转换 `SchemaValidationError` 回滚分支）在 `run_migrations()` 尚未被直接触发。
- 建议：可补充在进入 `baseline.apply_narrow_legacy_conversion` 前检查目标库 `pg_stat_activity` 连接数为 `0` 的用例，并在 `tests/mail_core/test_startup_migrations.py` 补测一条 `LEGACY` 形态漂移经 `main_module.run_migrations()` 拒绝且零写入的用例。

## 结论

- 改测方向复核：唯一既有测试修改为 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:294-297`，将随 `20261128_0008` 成为新 `head` 而过时的 `CURRENT_HEAD_REVISION == "20261126_0007"` / `get_heads() == ["20261126_0007"]` 与 `command.upgrade(cfg, "head")` 调整为与 `tests/mail_core/test_t090_migration_0006.py:147-150` 一致的 `>= "20261126_0007"`、`get_heads() == [CURRENT_HEAD_REVISION]` 及 `command.upgrade(cfg, "20261126_0007")`（保留 `0006 <-> 0007 -> head` 往返与全部 `0007` 目录去重/状态迁移断言）；该调整符合规格演进与 `task.md` 约束，并在 `progress.md` 明确写明理由，无「迁就实现 Bug」的改测。
- 本轮新发现：3 条（0 critical，0 important，3 minor）。
- 未进表的提示：`tests/mail_core/test_t096_fixes_unit.py:10` 存在未使用的 `SimpleNamespace` 导入；`tests/mail_core/test_t096_migration_and_patrol.py:111-114` 在构造 `Sent` 测试目录时填入 `role='inbox'`（不影响 `sync_checkpoints` 水位回填验证语义）；Playwright E2E 首轮复跑在最后一条 `tests/e2e/smoke.spec.ts:237` 的 `browserContext.close` 收尾阶段出现一次偶发 trace 文件 `ENOENT`（`recording50.network`），紧接完整重跑 26/26 全部通过。
- 总体判断：新增单元测试与真实 PostgreSQL 集成测试均直接触达生产逻辑且先红后绿证据完整，危险模式扫描未见恒真断言、非法弱化或跳过掩盖，0 个 blocking finding，全部 AC 复验为 `TICK-VALID`，结论 PASS。
- 系统性 follow-up：无（经 `.repo_template/scripts/task.py list` 核对无重复未闭环基础设施缺口）。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。独立重跑 `scripts/run-mail-core-tests.sh run --no-cov -k "test_t096_migration_and_patrol or test_t8_real_0030_legacy_shape_upgrades_via_startup or test_ac001_migration_0007_replaces_sync_status_and_coalesces_duplicates"` 与单元测试 `test_baseline_unit.py::test_startup_entry_reads_state_via_baseline_helper` 全部通过（且核对 `.scratch/test_runs/81426545e5384dc780ebb39ec93cd9a5` 先红记录 `[1] == [0]` 与 `0b57fa1146914711a5c8999a1fb85e42` 独立通过记录），验证 `run_migrations()` 写前关闭只读检查事务、`0030` 真实原地升级至 `20261128_0008` 及 `0007 -> 0008` `last_delta_settled_at` 精确回填。
- AC-002：TICK-VALID，re_verified。核查 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:294-369` 解除旧头硬编码并与 `test_t090_migration_0006.py` 边界对齐，且独立在真实 PostgreSQL 重跑 `test_ac001_migration_0007_replaces_sync_status_and_coalesces_duplicates` 通过。
- AC-003：TICK-VALID，re_verified。独立在真实 PostgreSQL 重跑 `test_ac003_patrol_short_circuit_zero_patrol_writes_and_clears_cooldown_on_recovery` 与单元测试 `test_ac003_patrol_and_readiness_avoid_runtime_dunder_import` 通过（对应先红失败 `assert 3 == 1` 与 `__import__` 检出），验证短路后兄弟目录零探测/零写 `folder_patrol_status`、冷却过期恢复清理冷却键及移除动态 `__import__`。
- AC-004：TICK-VALID，re_verified。独立运行 `KKMAIL_TEST_MODE=unit PYTHONPATH=src .venv/bin/python -m pytest tests/mail_core/test_t096_fixes_unit.py tests/mail_core/test_t095_contract_unit.py tests/mail_core/test_baseline_unit.py tests/mail_core/test_config.py tests/mail_core/test_a104_pool_kwargs.py tests/mail_core/test_a294_healthcheck_env.py -v --no-cov`（59 passed），验证 `load_config({})` 5 项预算字段与 `IdleWatcherConfig().quota` 及 `loader.py` AST 均派生自 `runtime_budget`。
- AC-005：TICK-VALID，re_verified。独立重跑上述单测与 PG 测试 `test_ac005_isolated_runtime_does_not_touch_shared_tmp_liveness` 通过，验证 `MAIL_CORE_DATA_DIR` 默认戳隔离、分布式模式下 `/ready` 逻辑忽略 `/tmp` 残留戳而嵌入式模式校验戳，以及 `tests/mail_core/runtime_isolation.py:106` 对 `MAIL_CORE_LIVENESS_STAMP` 的隔离。
- AC-006：TICK-VALID，trust_prior。独立重跑并全部通过模板契约（389 passed, 1 skipped）、敏感扫描（38 files 0 违规）、OpenAPI（46 paths 一致）、依赖锁校验、前端 vitest/`openapi:check`/`css:check`/`tsc -b`/`build`（56 files, 599 passed）、桌面端 `npm test`、Playwright E2E（重跑 26 passed）及双 Compose 校验，并核查 `docs/specs/mail_sync_and_storage.md` 与 `docs/blueprint/testing.md` 更新；35 分钟全量 100% 后端 PostgreSQL 套件复核自最新代码修改后的 `.scratch/test_runs/3c517178d7cd4a24a3ee042a62d12a77/test_summary.json` 与 `junit.xml`（2335 passed, 0 failed, 2 skipped，含 4 项真实 IMAP 协议测试全部通过）。

coverage = 5 / 6

verdict: PASS
