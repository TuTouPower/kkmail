---
tid: "t039"
slug: "folder_stats_scope_truth"
title: "保持邮件数量统计与查询范围一致"
status: "done"
branch: "t039_folder_stats_scope_truth"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "852c01372e17a4d858050eb2e9fed148870e5495"
depends_on: ""
conflicts_with: ""
note: "来源：审查确认缺少目标文件夹时合计全目录、部分账号失败时显示不完整的全局总数。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

实现与证据：

- MessageList 仅取目标 folder/role 统计；目标 role 缺失按 0 计。全账号统计任一请求失败时返回未知，列表显示 `—`，不展示成功账号小计。
- 全账号统计请求尚未返回且邮件行已加载时仍显示统计未知；全部账号响应成功后才展示完整数量。
- Sidebar fallback 仅取 inbox role 的 unread_count；无 inbox、缺 unread_count 或请求失败均记为未知，账号徽标和全局徽标显示 `-`。
- 新增 MessageList/Sidebar 组件测试覆盖单账号缺 role、全账号部分失败、全账号成功、跨账号缺 role、Sidebar 无 inbox；既有测试覆盖 Sidebar fallback 请求失败。
- 共享约定由 t040 集中更新，本 task 未改 blueprint。
- Round 1 review finding `t039_gen_f001` 已修：延迟统计响应测试验证邮件行先出现时仍显示未知，响应齐全后显示准确合计。
- 验证：前端 216 项测试通过；MessageList/Sidebar 目标测试 34 项通过；TypeScript、生产构建、lint 通过；stub E2E 8/8、真实全栈 E2E 3/3 通过。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T08:34:21+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t039_gen_f001|important|已修|统计响应未完成时，列表不再将已加载行数显示为全账号总数|src/frontend/src/components/MessageList.tsx:220；src/frontend/src/components/MessageList.test.tsx:223|

### Round 2 (2026-10-23T08:37:01+08:00)

Round 2 零 finding。独立 reviewer 复验 `t039_gen_f001` 已消除，AC-001 至 AC-004 全部 PASS；reviewed_scope：`deba6f7b41c7e43a`。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：AC-001 至 AC-004 全部满足
- 测试：`npm test` 216 passed；MessageList/Sidebar 34 passed；`npx tsc -b`、`npm run build`、`npm run lint` 通过
- 黑盒：`npm run test:e2e` 8 passed；`scripts/run_full_stack_e2e.py` 3 passed，临时数据库清理成功
- review：Round 1 的 `t039_gen_f001` 已修；Round 2 独立 review PASS，0 新 finding
- AC 证据：见 `handoff.json`

### 结果摘要

- 统计只展示与目标查询 scope 一致的数据；统计未完成、失败和缺少 inbox 统计均显示未知。Round 1 review finding 已修，Round 2 review PASS。实现与验证证据见 `handoff.json`。
