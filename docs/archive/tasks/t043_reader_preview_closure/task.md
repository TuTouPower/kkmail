---
tid: "t043"
slug: "reader_preview_closure"
title: "核验正文摘要隔离并闭环原修复记录"
status: "done"
branch: ""
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "来源 p022；原 main 修复 commit 4c28237、4c4dd7a 已合入，本 task 核验当前实现与回归后闭环文档。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 当前主干已有 `4c28237`、`4c4dd7a`。已核对 MessageReader 含 HTML 摘要加载/空正文/解析失败/请求失败回归及后端只读预览用例；前端回归与 general review 已通过；最终 PostgreSQL 全量 477 passed / 0 skipped。
- 工具状态说明：`task.py edit` 无 status 参数，`start` 必须建立 worktree；用户明确要求直接 main，因此不创建假 worktree、不伪造 active/done。front matter 保持脚本登记的 backlog，实际实施与验证事实记录于正文。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T19:17:52+08:00)

Round 1 零新增 finding；general 审查 PASS，见 [review_general.md](review_general.md)。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部行为验收、审查与门禁通过；实现已在 main，pending 已闭环。
- 测试：前端全量 260 passed；TypeScript、生产构建、lint、OpenAPI/CSS 检查通过。模板契约 149 passed / 1 skipped；桌面单元与打包冒烟通过。最终串行 PostgreSQL 全量 477 passed / 0 skipped（378.17s），运行 e9e0192dae624ce980a1ae3ee8fe66b3，测试库清理成功。
- 黑盒：stub E2E 13 passed；真实全栈 E2E 串行运行 8 passed。首轮与 stub 并行构建 dist 冲突导致 HTTP 500，定位后改为串行构建/运行并通过；未部署生产。
- review：general 审查 PASS，见 [review_general.md](review_general.md)。
- AC 证据：见下表；直接 main 实施，不生成或伪造 worktree `handoff.json`。

|AC|实际证据|
|---|---|
|AC-001|`MessageReader.test.tsx` 含 HTML body_preview 与 body 空值、archived true/false/null 回归；当前前端全量通过。|
|AC-002|`MessageReader.test.tsx` 加载/请求失败/解析失败/空正文互斥断言及正常 html/text 渲染用例；当前前端全量通过。|
|AC-003|`test_list_body_preview_is_read_only_and_preserves_provider_snippet` 核验服务商摘要原值、展示 fallback 与查询不写回；最终串行 PG 全量 477 passed / 0 skipped。|
|AC-004|p022 已记录实际 main commit 4c28237、4c4dd7a 与本轮验证信息，移除“未提交”陈旧描述。|

### 结果摘要

- 修复提交：`4c28237、4c4dd7a`。
- 核验现有 main 正文/摘要隔离修复，更新 p022 过时状态；未重复修改正文渲染实现或运行邮件数据。
- 最终 PG 全量：477 passed / 0 skipped；不变更脚本状态。

## 最终全量验证说明

- 注记：本节所述全量运行（运行 `e9e0192dae624ce980a1ae3ee8fe66b3`）为 t041–t043 同批联合验证，三份 task 共用同一运行记录，非各 task 独立运行。
- 真实 IMAP 与 PostgreSQL 全量串行运行：477 passed / 0 skipped，只有既有 Starlette 弃用警告；运行 `e9e0192dae624ce980a1ae3ee8fe66b3`，正常清理本轮测试库。
- 首轮两个旧夹具失败已补明确输入并保持原预期。第二轮与 IMAP 定向并行共用测试邮箱，目标邮件被另一套件清理；停止并行后最终全量通过。未因环境失败修改生产行为。
- 未部署生产，未改写运行容器数据。

## 直接 main 执行归档补记（2026-10-23T21:29:04+08:00）

- 状态修正时间：2026-10-23T21:29:04+08:00；归档提交 `8b826b2c` 将 front matter 状态由 backlog 修正为 done 并迁入 `docs/archive/tasks/`。正文实施笔记中「front matter 保持脚本登记的 backlog」为执行时流程限制记录，由本节更新。
- 实际执行分支：main；执行 commit：`4c28237`、`4c4dd7a`（原 main 修复，本 task 核验当前实现与回归后闭环）。
- 依据：核验已通过且最终 PostgreSQL 全量 477 passed / 0 skipped，见正文实施笔记与收尾报告；本任务直接在 main 完成，未创建登记 worktree/attempt，不补造 handoff。
