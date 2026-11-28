---
pid: "p105"
slug: "t096_minor_followups"
status: "closed"
resolution: "transferred"
reason: "已按当前主干核实并转办：t097 巡检账号失败与半开租约，t098 Worker 启动与就绪，t099 迁移执行器，t100 IDLE 生命周期。四项均通过创建检查。"
fix_ref: "t097,t098,t099,t100"
---
# p105 t096 测试审阅 minor follow-up

- 来源：t096 遗留（Round 1 `review_test.md` 3 条非阻断 `minor`：`t096_test_f001` / `t096_test_f002` / `t096_test_f003`，及 `review_code.md`/`review_test.md` 未进表清理提示）
- 内容：在不改产品行为的前提下补强 `t096` 边界测试深度与代码/测试整洁度：（1）`tests/mail_core/test_t096_migration_and_patrol.py` 增补预置 `FolderPatrolStatus` 行在同账号短路后的 `last_probe_at`/`last_probe_failures` 不变断言、冷却期 `now + 60s` `skipped_not_due` 断言、`FailureDomain.AUTH` 认证短路与 `provider_factory` 异常短路用例，并在进入 `baseline.apply_narrow_legacy_conversion` 前探查 `pg_stat_activity` 连接数归零，同时在 `tests/mail_core/test_startup_migrations.py` 补测 `LEGACY` 漂移/回滚拒绝分支（`t096_test_f001`, `t096_test_f003`）；（2）`tests/mail_core/test_t096_fixes_unit.py` 补 `MAIL_CORE_EMBEDDED_WORKER=0` 且显式 `MAIL_CORE_LIVENESS_STAMP` 陈旧校验、`Path(env_val).parent == tmp_path` 断言并清理第 10 行未用 `SimpleNamespace` 导入，`tests/mail_core/test_t096_migration_and_patrol.py:111-114` 测试夹具 `Sent` 目录角色写正为 `sent`（`t096_test_f002`）；（3）视需要拆分已超 740 行的 `src/mail_core/sync/idle_watcher.py`；因全量 2335 后端 PG 套件已通且为冻结 `t096` 已审 `reviewed_scope` 避免无行为收益的重审与 35 分钟重跑，按惯例延后收敛。
- 处理：t097,t098,t099,t100；resolution=transferred；reason=已按当前主干核实并转办：t097 巡检账号失败与半开租约，t098 Worker 启动与就绪，t099 迁移执行器，t100 IDLE 生命周期。四项均通过创建检查。
