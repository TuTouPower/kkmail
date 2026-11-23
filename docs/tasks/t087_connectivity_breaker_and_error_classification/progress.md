---
tid: "t087"
slug: "connectivity_breaker_and_error_classification"
title: "账号连接熔断连续语义与传输错误分类根治"
status: "done"
branch: "t087_connectivity_breaker_and_error_classification"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "82b86fb716e34a0fe71bbc317bad75ac212f21e5"
spec_source_sha: "82b86fb716e34a0fe71bbc317bad75ac212f21e5"
depends_on: ""
conflicts_with: ""
note: "来源 p088；非连续失败累计 + 非网络错误误判导致 unreachable 假阳性，含 UI 盲区与陈旧性"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 熔断状态机从「累计计数 + 固定首失败时间」重写为 5 分钟滑动窗口内的连续失败时间戳集合：`accounts/health.py` 的 `CFG_FAILURE_TIMESTAMPS` 取代旧 `connectivity_failure_count` / `connectivity_first_failure_at`，窗口外失败开启新 streak；仅窗口内累计≥5 且跨度≥5 分钟才升级 `unreachable`，任意传输成功清零。
- 故障分类从自由文本 marker 匹配改为结构化分发：`sync/context.py` 定义 `FailureDomain` / `FailureClassification`，只按异常类型、HTTP status、errno 与生产者附加的 `failure_code` 判定；`delta.py` / `reconcile.py` 在脱敏边界统一写入 `failure_code`；删除 `is_permanent_auth_error` / `is_transient_network_error` 及 `_TRANSIENT_MARKERS` / `_AUTH_MARKERS`。
- 恢复闭环：`accounts/health.py` 增加 `recheck_unreachable`（15 分钟无新失败降级为 `degraded`），由 Worker 周期 sweep 调用；IDLE 建连成功也调用 `record_connectivity_success`；连接态迁移通过 `OutboxEvent(account.updated)` 广播，前端已有失效链路直接复用。
- 测试：删除把跨时段累计固化为预期的旧用例（语义由实现反推），新增跨天不升级、结构化分类反向样本、事件广播与 15 分钟复核用例；`test_worker_loop.py` 的脱敏用例改为真实传输异常，避免文本匹配支撑假绿。
- 文档：`docs/blueprint/conventions.md:160`、`docs/specs/mail_sync_and_storage.md`、`docs/blueprint/testing.md` 同步；spec tasks 登记 t087。
- 工具链限制：p088 在立项时已置 `closed/transferred`（`fix_ref: t087`），`pending.py close` 拒绝把已闭环条目改为 `resolved`，故保留转办终态，双向引用成立；未手工改写 front matter。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

所有轮次的 finding 在此唯一登记，ID 不重复：

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t087_code_f001|important|撤回|code reviewer Round 2 独立复核同意撤回：finding 称 `Sidebar.tsx:271-277` 是唯一 notice 渲染点有误，`Sidebar.tsx:350` 在 `folders.length>0` 分支已渲染 `{notice && ...}`，组件测试断言有文件夹时红字与「收件箱」并存|`src/frontend/src/components/Sidebar.tsx:350`|
|t087_code_f002|important|已修|熔断连续性改为「相邻失败间隔≤5 分钟」，跨度独立判定；按真实 backoff 序列第 10 次失败（t=511s）可达 unreachable，跨天仍 degraded|`src/mail_core/accounts/health.py:_failure_streak` / `tests/mail_core/test_account_health_state_machine.py`|
|t087_code_f003|minor|已修|`classify_failure` 拆为 `_classify_exception` 与 `_classify_result_dict`，圈复杂度回落|`src/mail_core/sync/context.py`|
|t087_code_f004|minor|已修|docstring 改为「相邻间隔≤窗口、首失败距今≥窗口」语义，与实际状态机一致|`src/mail_core/accounts/health.py:155-161`|
|t087_test_f001|important|已修|补组件 + 缓存集成用例：恢复 connected 后经 `account.updated` 失效，断言红字消失|`src/frontend/src/components/Sidebar.test.tsx`|
|t087_test_f002|minor|已修|新增按真实 `backoff_seconds` 序列推进的升级用例|`tests/mail_core/test_account_health_state_machine.py`|

Round 1 修复后全部门禁重跑：后端 unit 1465 passed、模板契约 388 passed、前端单测 593 passed + tsc/build/lint 通过、桌面单测通过、黑盒 E2E 23 passed、敏感扫描 0 违规。AC 撤回后逐条重勾。Round 2 两轴 verdict 均 PASS（test 轴 0 新 finding、7 条 AC 全 TICK-VALID；code 轴 f004 为唯一 minor）。Round 3 刷新指纹：f004 独立复核已消除、0 新 finding、两轴 PASS。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：后端 unit 1465 passed / 498 skipped（`test_account_health_state_machine.py` 14 passed）；模板契约 388 passed / 1 skipped；前端 vitest 55 文件 593 passed + `tsc -b` / `npm run build` / `oxlint --deny-warnings` 通过；桌面 12 文件单测通过（oauth 按设计 skip）；敏感文档扫描 0 违规。
- 黑盒：`npm --prefix src/frontend run test:e2e` 23 passed（stubApi 快速 E2E，含 360px 几何门禁）。
- review：full 三轴收尾 `code_verdict=PASS` / `test_verdict=PASS` / `overall=PASS`，`review_scope=ok`、`ac_review=ok`、`round=3`、`next_action=finalize`；Round 1 两条 important 中 f001 撤回、f002 已修，Round 2 minor f004 已修，Round 3 刷新指纹。
- AC 判定：见 `task.md` 行内打勾（7/7 已勾选）。

### 结果摘要

- 根因级根治：`connectivity_state` 熔断改为相邻失败间隔≤5 分钟、累计≥5 且首失败距今≥5 分钟才升级 `unreachable`；故障分类改为异常类型/status/errno/`failure_code` 结构化分发；15 分钟有界复核 + IDLE 建连成功复位 + `account.updated` 广播，消除「偶尔出现又自愈」的假阳性。
- 遗留：无。工具链观察：`pending.py close` 拒绝把已 `closed/transferred` 的 p088 改为 `resolved`，保留转办终态与双向引用，未手工改 front matter；`task.py review-status --task-dir` 在本 worktree 曾把 repo root 误解析到主仓（测试 reviewer 观察），本会话用显式 `--task-dir` 相对路径后正常，需模板侧确认。

### 长期文档闭环

在 active spec 的 front matter `tasks` 清单中登记当前 tid（`task.py specs list --json`）；无长期 spec 变更时写 `- specs_index: not_applicable: 具体原因`。正式 spike 须有 report、现存 finding、采纳结论、后续 tid 或无需后续理由；finish 会检查这些引用。
