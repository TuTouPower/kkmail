---
tid: "t038"
slug: "reader_recipient_truth"
title: "避免把账号邮箱显示为邮件收件人"
status: "done"
branch: "t038_reader_recipient_truth"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "852c01372e17a4d858050eb2e9fed148870e5495"
depends_on: ""
conflicts_with: ""
note: "来源：审查确认 To 为空时阅读器回退为账号邮箱。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. TDD 新增多收件人、空 To、缺失 To/Bcc-only、账号归属分离与切换邮件用例；修复前 3 个空/缺失 To 与切换用例均复现账号邮箱错误显示。
2. `MessageReader` 删除独立账号查询及 To 推测回退；MR07 仅展示详情 API 的 `to`，空值显示“未提供”。账号邮箱仍单独显示在阅读器 toolbar 的归属位置。
3. 前端全量测试、类型检查、生产构建、lint、UI E2E 与真实全栈 E2E 均通过。
4. Round 1 review 指出详情仍在加载或请求失败时不能显示“未提供”；新增两状态断言，复现问题后改为仅在详情加载成功时渲染 MR07。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T08:30:25+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t038_gen_f001|important|已修|详情加载中/失败时隐藏收件人行，详情成功后再按 API To 显示地址或“未提供”|src/frontend/src/components/MessageReader.tsx:182; src/frontend/src/components/MessageReader.test.tsx:251,300|

### Round 2 (2026-10-23T08:34:01+08:00)

Round 2 零 finding。

无 finding 时写“Round N 零 finding”。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`MessageReader.test.tsx` 23 passed；前端全量 38 个测试文件、214 项 passed；OpenAPI 与 CSS token 检查通过；`npx tsc -b`、`npm run build`、`npm run lint` 通过
- 黑盒：`npm run test:e2e` 8 passed；`scripts/run_full_stack_e2e.py` 3 passed
- review：Round 1 finding 已修，Round 2 independent review PASS（scope: `3ec8fbc6a0fd018d`）
- AC 证据：见 `handoff.json`

### 结果摘要

- To 仅来自详情 API；详情尚未加载或加载失败时隐藏收件人行，详情成功且 To 为空时显示“未提供”；账号归属单独保留在 toolbar。
