---
pid: "p084"
slug: "sync_migration_orphan_link_assertion"
status: "closed"
resolution: "resolved"
reason: "新增临时库迁移专项测试：在 0002 注入 job_id=NULL 关联，升级到 head 后断言关联清除、目标 failed/sync_incomplete、请求 failed；临时变更清理 SQL 可稳定复现失败；迁移专项 13 passed，test_cmd 全通过"
fix_ref: "main"
---
# p084 t082 迁移清理悬挂关联缺可执行断言

- 现象：t082 的 Alembic 迁移 `20261122_0003_real_job_links` 在升级时删除 `job_id IS NULL` 的历史关联，并把其目标收敛为可读失败 `sync_incomplete`。该行为只由「全新库升级到 head」的通用迁移冒烟覆盖，没有一条测试先构造 0002 版本的悬挂关联再升级到 0003 并读回断言。
- 影响：迁移数据修复路径（删除悬挂关联、目标失败收敛）的回归无法被独立捕获；若后续改动破坏该 SQL，通用空库升级测试仍会通过。
- 根因：测试基础设施建设缺口，非产品缺陷。现有迁移测试基础设施（`tests/mail_core/test_migration_validation.py`）使用共享当前 head 数据库，未提供「在受控临时库上升级到指定中间版本、注入数据、再升级到 head」的可复用夹具。
- 测试缺口：补一条真实 PostgreSQL 测试——在临时库升级到 `20261112_0002`，注入 `sync_request_target_jobs.job_id IS NULL` 的关联与对应 open 目标，升级到 `20261122_0003`，断言关联被清除、目标 `state=failed` / `error_code=sync_incomplete` / `safe_error` 可读。
- 线索：t082 review `t082_test_f001`（minor，未阻断 PASS）；`docs/tasks/t082_sync_request_completion_by_data_watermark/review_test.md`。
- 处理：main；resolution=resolved；reason=新增临时库迁移专项测试：在 0002 注入 job_id=NULL 关联，升级到 head 后断言关联清除、目标 failed/sync_incomplete、请求 failed；临时变更清理 SQL 可稳定复现失败；迁移专项 13 passed，test_cmd 全通过
