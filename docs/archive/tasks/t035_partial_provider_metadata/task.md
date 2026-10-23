---
tid: "t035"
slug: "partial_provider_metadata"
title: "保留 Graph 局部状态与未知附件元数据语义"
status: "done"
branch: "t035_partial_provider_metadata"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "852c01372e17a4d858050eb2e9fed148870e5495"
depends_on: ""
conflicts_with: ""
note: "来源：审查复现；Graph delta 缺字段生成 false，IMAP/Gmail 未提供附件标记却覆盖已归档值。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 复核确认 Graph Delta 将缺失的 `isRead` / `flag.flagStatus` 默认成 `false`；IMAP 与 Gmail 的 metadata parser 将未提供附件状态默认成 `false`，`upsert_messages` 会据此覆盖本地值。
- 先新增 parser 与数据库行为测试。RED 阶段 `test_parse_graph_delta_preserves_field_presence_for_status_updates` 和 `test_provider_metadata_marks_unknown_attachments_without_fabricating_false` 均因缺失字段合成 `false` 失败；随后实现 Optional 状态与更新时跳过未知值。
- 为移除旧断言 `test_parse_graph_delta_flag_only_without_content_metadata` 记录原因：该测试要求缺失状态合成为 false，正是本 task 修复的破坏性行为；新测试分别覆盖只读 read、只读 flag、带内容的部分状态、明确 false 与未提供附件状态。
- Round 1 test review 指出 Graph parser 新测试曾在旧函数位置改名替换。已整体删除旧测试块，并在文件末尾新增独立 `test_graph_delta_partial_status_field_presence_contract`，保留新契约覆盖。
- 未修改 `docs/blueprint/`；长期约定由 t040 统一更新。累计邮件同步规格已补充 AC-011/012。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T08:43:33+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t035_code_f001|minor|撤回|接受审查中的启发式复杂度提示，但不抽 helper；3 处字段存在性判断语义直观，增加间接层无行为收益|src/mail_core/providers/parsing/graph_delta.py:21|
|t035_test_f001|minor|已修|整体删除旧测试块，并在文件尾新增独立 parser 契约测试；旧断言对应破坏性默认值，替换原因已记录|tests/mail_core/test_gmail_graph_contracts.py|

### Round 2 (2026-10-23T08:52:21+08:00)

- 前轮 finding：`t035_code_f001` 按上述理由撤回；`t035_test_f001` 已修并经复核确认。
- 本轮新增 finding：0；code/test verdict 均 PASS，scope `d007d7f37a900891`。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：模板契约 149 passed；定向后端 PostgreSQL 测试 31 passed；完整后端测试 402 passed / 0 skipped；parser TDD RED 2 failed（按预期）后修复；
- 黑盒：前端浏览器 E2E 8 passed；全栈 E2E 3 passed。
- review：Round 1 / Round 2 code/test 均 PASS；code 轴 minor 已评估撤回，test 轴 minor 已修。
- AC 证据：见 `handoff.json`

### 结果摘要

- Graph delta 与 metadata 仅更新明确返回的状态；IMAP/Gmail 附件状态未知时保留已归档结果。没有数据库 schema 变更或历史数据回写。
- Full code/test review Round 1 与 Round 2 均 PASS；旧测试已整体删除并以独立契约测试覆盖；未解决 finding：无。
