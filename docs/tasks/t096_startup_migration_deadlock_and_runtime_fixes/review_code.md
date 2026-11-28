# Task review t096（reviewer_focus: 代码）

- task：`t096_startup_migration_deadlock_and_runtime_fixes`
- spec：`docs/tasks/t096_startup_migration_deadlock_and_runtime_fixes/task.md`
- diff_anchor：`bac5baebef3a5c1d37c53e3f3f4cdd006f323582`
- target：`git diff bac5baebef3a5c1d37c53e3f3f4cdd006f323582`
- round：1
- reviewed_at：2026-11-28T15:36:04+08:00

reviewed_scope: 0d2fd3431fd48ccf

## Findings

无（已完成安全、正确性、契约·Breaking、性能·资源、架构·可维护性、健壮性·可观测及文档·规格 7 视角审查，未发现阻断或待修代码缺陷）。

## 结论

- 本轮新发现：0 条
- 未进表的提示：
    - 文件过大（实现源码 ≥400 行且本 task 净增行数）：`src/mail_core/sync/idle_watcher.py` 741 行（净增 1 行，仅将 `IdleWatcherConfig.quota` 默认值改为引用 `runtime_budget.DEFAULT_IDLE_QUOTA`），建议后续拆解；未达 800 行阻断线且无因此导致的可观测缺陷。
    - 圈复杂度 ≥10 提示（本 task 均未增加分支）：`src/mail_core/sync/patrol.py:schedule_folder_status_patrol`（McCabe 约 18，本次删减短路重复分支并外提 `_clear_cooldown`）；`src/mail_core/__main__.py:run_migrations`（McCabe 约 10-11，本次收敛只读检查作用域并消除重复条件块）；`src/mail_core/readiness.py:read_worker_active_via_core`（McCabe 约 10）。
    - 7 视角正交巡检已覆盖全部 diff 路径：只读检查连接在 `finally: check_engine.dispose()` 彻底关闭后再进入写路径；`patrol.py` 短路跳过不写 `folder_patrol_status` 亦不误计 `result.failed` 且恢复探测成功后清理冷却键；`patrol.py` 与 `readiness.py` 均无运行时 `__import__`；`loader.py`/`idle_watcher.py` 并发预算统一派生自 `mail_core.runtime_budget`；`liveness.py`/`readiness.py`/`tests/mail_core/runtime_isolation.py` 数据目录与分布式模式边界清晰；`docs/specs/mail_sync_and_storage.md`（§二第5条、§八第1条及 front matter `tasks`）与 `docs/blueprint/testing.md` 同步准确。
- 总体判断：全部 6 条验收标准在实现层真实完整落地且不变量守住，代码无未解决 critical / important 或 minor finding，判定 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。核对 `src/mail_core/__main__.py:54-132` 将 `read_database_state(conn)`/`plan_migration`/`verify_for_plan` 收敛至 `with check_engine.connect()` + `finally: check_engine.dispose()` 块内，全部写路径与 `check_only` 返回均在释放只读事务锁后执行，且实测真实 PG 49 用例（含 `test_t8_real_0030_legacy_shape_upgrades_via_startup`、`test_ac001_run_migrations_closes_check_connection_before_upgrade`、`test_ac001_migration_0008_backfills_last_delta_settled_at_from_updated_at`）全部通过。
- AC-002：TICK-VALID，re_verified。核对 `tests/mail_core/test_t092_orthogonal_folder_lifecycle.py:294-297, 353-369` 改为 `CURRENT_HEAD_REVISION >= "20261126_0007"` 与 `get_heads() == [CURRENT_HEAD_REVISION]` 并验证 `0006 <-> 0007 -> head` 迁移往返，且在真实 PG 复跑通过。
- AC-003：TICK-VALID，re_verified。核对 `src/mail_core/sync/patrol.py:71-77, 264-310` 对 `short_circuited` 同账号后续目录直接 `continue` 零探测零写盘零失败计数、首失败写单条 `FolderPatrolStatus` 与冷却、探测成功调用 `_clear_cooldown(account)` 并由 `_record_attempt` flush，且 `patrol.py` 与 `readiness.py` 零 `__import__`，真实 PG 与单元测试复跑通过。
- AC-004：TICK-VALID，re_verified。核对 `src/mail_core/config/loader.py:89-94, 123` 与 `src/mail_core/sync/idle_watcher.py:79` 均从 `mail_core.runtime_budget` 派生，与 `src/mail_core/config/models.py:37-44, 67` 一致，且复跑 `tests/mail_core/test_t096_fixes_unit.py` 直接断言 `load_config({})` 与 `IdleWatcherConfig()` 及 AST 无字面量重复全部通过。
- AC-005：TICK-VALID，re_verified。核对 `src/mail_core/liveness.py:20-35` 支持 `MAIL_CORE_LIVENESS_STAMP` -> `MAIL_CORE_DATA_DIR/worker-liveness.json` -> `DEFAULT_STAMP_PATH` 并自动建父目录，`src/mail_core/readiness.py:133-144` 仅在显式戳路径或 `MAIL_CORE_EMBEDDED_WORKER != "0"` 时校验本地戳，`tests/mail_core/runtime_isolation.py:106` 隔离用例戳路径至 `tmp_path/liveness.json`，单元测试与 PG 隔离测试复跑通过。
- AC-006：TICK-VALID，trust_prior。已直接核对 `docs/specs/mail_sync_and_storage.md` 与 `docs/blueprint/testing.md` 更新并独立复跑通过全部快速门禁（模板契约 389 passed/1 skipped、敏感扫描 38 files 0 违规、OpenAPI 46 paths 校验、前端 56 files 599 passed/`tsc -b`/`build`/`openapi:check`/`css:check`、桌面端全套测试、双 compose 校验）、Playwright E2E（26 passed）及 49 条定向真实 PG 迁移/巡检测试；100% 后端 PG 全量（2335 passed, 2 skipped, 0 failed, `not_executed: []`）依代码修改后生成的 `.scratch/test_runs/3c517178d7cd4a24a3ee042a62d12a77/test_summary.json` 产物确认。

coverage = 5 / 6

verdict: PASS
