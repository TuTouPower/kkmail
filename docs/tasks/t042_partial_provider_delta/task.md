---
tid: "t042"
slug: "partial_provider_delta"
title: "保留服务商部分更新中未返回字段"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "来源 p025；用户授权直接 main 修复。区分字段缺省与显式清空，拒绝不完整 Gmail hydration。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 用户授权直接在 `main` 修复；实现包含 supplied_fields、Graph 字段存在性、Gmail hydration 完整性检查、同页 partial/flag 顺序合并。实现已提交 `c755ebd`，审查 PASS；最终 PostgreSQL 全量 477 passed / 0 skipped。
- 工具状态说明：`task.py edit` 无 status 参数，`start` 必须建立 worktree；用户明确要求直接 main，因此不创建假 worktree、不伪造 active/done。front matter 保持脚本登记的 backlog，实际实施与验证事实记录于正文。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T19:17:52+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t042_code_f001|important|已修|同页同邮件部分字段与状态按响应顺序合并，避免只保留最后一条而丢数据。|`c755ebd`|

最终代码与测试审查均 PASS，见 [review_code.md](review_code.md)、[review_test.md](review_test.md)。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部行为验收、审查与门禁通过；实现已在 main，pending 已闭环。
- 测试：最终 partial/race/detail PG 定向 19 passed。前端全量 260 passed；TypeScript、生产构建、lint、OpenAPI/CSS 检查通过。模板契约 149 passed / 1 skipped；桌面单元与打包冒烟通过。最终串行 PostgreSQL 全量 477 passed / 0 skipped（378.17s），运行 e9e0192dae624ce980a1ae3ee8fe66b3，测试库清理成功。
- 黑盒：stub E2E 13 passed；真实全栈 E2E 串行运行 8 passed。首轮与 stub 并行构建 dist 冲突导致 HTTP 500，定位后改为串行构建/运行并通过；未部署生产。
- review：代码与测试审查均 PASS，见 [review_code.md](review_code.md)、[review_test.md](review_test.md)。
- AC 证据：见下表；直接 main 实施，不生成或伪造 worktree `handoff.json`。

|AC|实际证据|
|---|---|
|AC-001|`test_partial_graph_and_gmail_updates_preserve_omissions_and_apply_explicit_empty` 真实 PG 逐字段验证 Graph subject/from partial 保留遗漏值。|
|AC-002|同一真实 PG 用例验证显式空 subject/snippet/To/Cc 持久化清空，与 omitted 明确区分。|
|AC-003|同一用例覆盖 Gmail list/history metadata 无 snippet 时保留旧摘要，新 ID 首次插入仍无摘要。|
|AC-004|`test_gmail_rejects_incomplete_or_mismatched_hydration` 与 `test_gmail_hydration_failure_never_uses_partial_history_headers` 覆盖两入口缺 id/id-only/mismatch/GET 异常。|
|AC-005|`test_delta_application_combines_partial_changes_in_response_order` 覆盖 partial/flag/full/delete 顺序；既有真实本地意图保护回归保留。|

### 结果摘要

- 修复提交：`c755ebd`。
- Graph/Gmail 部分 projection 通过 supplied_fields 保留缺省字段，显式空值可清空；Gmail hydration 验证失败即阻断页，同页 partial/flag 按响应顺序合并。
- 最终 PG 全量：477 passed / 0 skipped；不变更脚本状态。

## 最终全量验证说明

- 真实 IMAP 与 PostgreSQL 全量串行运行：477 passed / 0 skipped，只有既有 Starlette 弃用警告；运行 `e9e0192dae624ce980a1ae3ee8fe66b3`，正常清理本轮测试库。
- 首轮两个旧夹具失败已补明确输入并保持原预期。第二轮与 IMAP 定向并行共用测试邮箱，目标邮件被另一套件清理；停止并行后最终全量通过。未因环境失败修改生产行为。
- 未部署生产，未改写运行容器数据。
