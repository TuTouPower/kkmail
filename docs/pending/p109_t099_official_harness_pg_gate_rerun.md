---
pid: "p109"
slug: "t099_official_harness_pg_gate_rerun"
status: "todo"
---
# p109 t099 官方 harness 后端全量 PG 套件复跑（云端无 Docker 未执行）

- 来源：t099 云端执行环境限制（2026-11-29）。
- 内容：t099 的 AC 已在云端自备的真实 PostgreSQL 16.6（theseus-rs 便携包，仓库固定 SHA-256）上实测通过——新增 `tests/mail_core/test_t099_migration_executor.py` 7 条与迁移相关回归套件（`test_startup_migrations`、`test_migration_validation`、`test_legacy_migration`、`tests/scripts/test_migrate_to_unified_baseline.py` 35 条、`test_t096` AC-001 两条）均以与提交版一致的副本在官方守卫链外执行。但云端 VM 无 Docker，官方 harness 的所有权守卫（`scripts/test_pg_runtime.py` 的 `guard_database`，硬绑 Docker 容器所有权记录）无法满足，后端全量 PG 套件（`scripts/run-mail-core-tests.sh run`）未在官方 harness 下执行。待 t099 集成到 Mac 主干时，在官方 harness 下复跑后端全量 PG 套件（含 t097 若新增 Alembic revision 后的集成 head 复验），通过后关闭本条。
- 处理：未开
