---
tid: "t076"
slug: "account_sync_state_and_retry_architecture_refactor"
title: "重构账号状态机与重试架构解耦凭据网络与执行态"
status: "done"
branch: "t076_account_sync_state_and_retry_architecture_refactor"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "20b61520c0837db9cd4c44506886bae6a507a1a2"
spec_source_sha: "20b61520c0837db9cd4c44506886bae6a507a1a2"
depends_on: ""
conflicts_with: ""
note: "来源 p075；按开发铁律彻底重构：废除单值 sync_status，正交解耦凭据/网络/执行态，重试回归 Worker 调度，前端精确呈现"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 迁移策略（Round 1 review 修正）：新增独立 Alembic revision `20261112_0002`（`down_revision=20261107_0001`）。`upgrade()` 加三列并把 `auth_failed`→`credential_state=invalid / sync_enabled=false`、`failed`→`connectivity_state=degraded` 后 drop `sync_status`；`downgrade()` 逆向恢复旧字段与取值。同步修正 `baseline.py` 分类层：新增 `CURRENT_HEAD_REVISION` 与 `UPGRADE_TO_HEAD` 动作，让仍盖印 `20261107_0001` 的已有库经 `python -m mail_core` 增量升级，而非被 `verify_baseline_schema` 拒绝启动；`_stamp_targets` 对新 head 库幂等 noop；离线工具对落后 revision 给出明确启动指引。所有单 head 硬断言统一更新为新 head。新增 `test_startup_migrations.py::test_t7` 用真实 PG 验证旧库升级与历史数据映射。定向 PG 263 passed 复验。
- 状态机单一权威：新增 `src/mail_core/accounts/health.py`，三维状态写入全部收敛于此；删除 `service.update_account_sync_status` 与 `handlers._recover_account_sync_status`（扫表自愈补丁）。
- 失败正交分类：`sync/context.py` 新增 `AccountFailureKind` / `account_failure_kind` / `is_transient_network_error`，扩展 `is_permanent_auth_error` 识别 401 / `invalid_grant` / `AUTHENTICATIONFAILED`；`resolve_sync_context` 支持 payload 顶层 `background`，后台静默失败不外溢。
- 重试回归框架：删除 `delta.py` 通用 provider 异常与 `engine.py` 通用异常段的私有 `enqueue_job` + 伪 `done`；扩展 `sync/jobs.py::reschedule_job(count_failure=True)` 实现「同一 job 行、递增 `failure_attempts`、指数退避、达 cap 转 `fail_job` 终态」；控制流类（rate_limit / lease_busy / fencing / cursor_invalid / capacity）保留既有 followup 语义。
- 周期性同步：`worker/main.py::schedule_periodic_inbox_sync` 入队 payload 显式注入 `{"background": True}`。
- 契约：`AccountDTO` / `AccountOut` 移除 `sync_status`，新增四字段；重跑 `export_openapi.py` 与 `openapi:gen`；前端 `Sidebar` / `SettingsModal` / `MessageList` 按结构化状态精确呈现，移除硬编码「同步失败，请检查账户设置」。Folder 级 `folders.sync_status` 全程保留。
- 并行实施：前端组件/测试、文档、后端测试三组由独立子代理在互不重叠文件组实施，主任务统一复核并以门禁验证。
- 既存门禁失败：`test_check_dep_locks`（uv 上游 lock 漂移）与 `test_check_doc_sensitive::test_repo_docs_gate_passes`（13 处历史 review 文档把 `[REDACTED_EMAIL]` 占位符 / `foo@bar.com` 示例误判为敏感数据）均在主仓 HEAD 复现，采纳前基线即存在，非本 task 引入；本 task 来源 p075 的真实邮箱已脱敏。按配置缺陷报告约定，任务结束后一并报告，不改动无关历史文档。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-12T08:52:23+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t076_code_f001|critical|已修|新增 0002 增量 revision + UPGRADE_TO_HEAD 分类层，已有库可升级且保留数据|src/mail_core/db/alembic/versions/20261112_0002_account_health_states.py:26|
|t076_code_f002|important|已修|熔断失败计数单调累计、仅成功清零，unreachable 可达|src/mail_core/accounts/health.py:130|
|t076_code_f003|important|已修|认证信号结构化（HTTP 401 / auth_failed code / invalid_grant）+ provider 层 PermanentAuthError|src/mail_core/sync/context.py:87|
|t076_code_f004|important|已修|handle_job finally 统一终态复位 sync_activity|src/mail_core/worker/handlers.py:253|
|t076_code_f005|minor|已修|reschedule_job(count_failure) 委托 fail_job 消除重复与分叉|src/mail_core/sync/jobs.py:460|
|t076_test_f001|important|已修|单维度守卫补双维度、前台超时明确断言 degraded|tests/mail_core/test_t061_idle_watcher.py|
|t076_test_f002|important|已修|删除 inspect.getsource 假测试，改由真实入队 payload 断言覆盖|tests/mail_core/test_worker_scheduler.py:84|
|t076_test_f003|minor|已修|补熔断双负向边界与真实 backoff 序列升级测试|tests/mail_core/test_account_health_state_machine.py:214|
|t076_test_f004|minor|已修|硬编码退避、补 attempts/priority/last_error 断言|tests/mail_core/test_account_health_state_machine.py:155|
|t076_test_f005|minor|已修|补 401 / AUTHENTICATIONFAILED / invalid_grant 分类测试|tests/mail_core/test_account_health_state_machine.py:190|
|t076_test_f006|minor|已修|补 reschedule 后 priority==55 真断言|tests/mail_core/test_account_health_state_machine.py:180|

### Round 2 (2026-11-12T09:10:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t076_code_f006|important|已修|narrow conversion post-check 仅豁免 accounts 四列，其余 drift 仍捕获并回滚|src/mail_core/db/baseline.py:404|
|t076_code_f007|important|已修|handle_job finally 覆盖认证失效后的早退分支|src/mail_core/worker/handlers.py:253|
|t076_test_f007|minor|已修|补 assert jobs 防空集真空通过|tests/mail_core/test_sync_hardening_a27_a28_a29.py:138|

### Round 3 (2026-11-12T09:35:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t076_code_f008|minor|已修|移除 \_evaluate_result 三处重复 \_finish_activity，finally 唯一收尾并统一退避中态|src/mail_core/worker/handlers.py:198|
|t076_test_f008|minor|遗留|LEGACY 真实 0030 形状正向 PG 用例属非阻断覆盖缺口，主链路由 test_t7 与结构探针覆盖|p076|

### Round 4 (2026-11-12T10:05:00+08:00)

Round 4 零 finding（code / test 双轴 PASS，7/7 AC TICK-VALID）。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：定向 PG 275 passed（迁移正向/逆向、旧库增量升级与数据映射、narrow conversion drift 拒绝、状态机、认证复位）与 134 passed（f008 修复复验）；后端 unit 1654 passed（2 个采纳前基线既存失败：`test_check_dep_locks` uv lock 漂移、`test_check_doc_sensitive` 历史 review 文档占位符/示例误判，均在主仓 HEAD 复现）；前端 vitest 586 passed + `tsc -b` / build / `oxlint` / `openapi:check` / `css:check`；模板契约 463 passed、桌面单测通过；最终全量 PG 门禁结果见 `.scratch/pg_gate6.log`。
- 黑盒：stubApi E2E 21 passed；全栈真实 FastAPI + PG + Worker + 生产 SPA Playwright 8 passed。
- review：full 级 4 轮，`review_code.md` / `review_test.md` Round 4 均 PASS；16 个 finding 全部处置（15 已修 / 1 遗留→p076），coverage 7/7，无 TICK-VOID。
- AC 判定：见 `task.md` 行内打勾（AC-001~AC-007 全部 TICK-VALID）

### 结果摘要

- 账号级单值 `sync_status` 彻底废除，改三维正交状态（`credential_state` / `connectivity_state` / `sync_activity` + `last_connectivity_error`）并收敛到单一权威 `src/mail_core/accounts/health.py`；删除私有重试与扫表自愈，重试统一回归 Worker `reschedule_job` / `fail_job`；周期后台故障不外溢；认证失效与传输抖动正交分类；前端按结构化状态精确呈现；Folder 级 `folders.sync_status` 全程保留。遗留只写引用：p076。

### 长期文档闭环

- specs_index：`docs/specs/account_connection.md` front matter `tasks` 已登记 `t076`。
- blueprint：`docs/blueprint/conventions.md`、`docs/blueprint/architecture.md`、`docs/guides/troubleshooting.md` 已按新状态机与熔断语义更新。
- 正式 spike：无（本 task 无未核实外部契约，`.scratch/t076_contract.md` 为一次性实施草稿，不入库）。
