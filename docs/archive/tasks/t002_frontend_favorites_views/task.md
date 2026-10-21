---
tid: "t002"
slug: "frontend_favorites_views"
title: "重构个人收藏为收件箱未读与已发三折叠树"
status: "done"
branch: "t002_frontend_favorites_views"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "20819f0569606224f2e519c14c2f221bae4e2e4e"
depends_on: "t001"
conflicts_with: ""
note: ""
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. `mailStore.ts`：扩展 `FavoriteCategory` 与 `ViewState`（支持 `category: inbox | unread | sent` 及其账号维度），`setView` 保留重置行为。
2. `Sidebar.tsx`：重构个人收藏为「所有收件箱」、「所有未读」、「所有已发邮件」三折叠树，各自独立展开折叠；收件箱父子项展示未读数角标，未读与已发不展示角标；点击父项与子项切换对应分类视图。
3. `MessageList.tsx` 与 API：根据视图分类向 `/api/mail/inbox` 传入对应 `folder_role`（收件箱 `inbox`，已发 `sent`，未读 `inbox`+`is_read=false`）。
4. 测试覆盖：更新 `Sidebar.test.tsx`、`MessageList.test.tsx`、`mailStore.test.ts`，并通过端到端冒烟测试。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-22T05:07:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`npm test && npx tsc -b && npm run build` (117 unit tests passed)、`(cd src/desktop && npm test)`、`pytest .repo_template/tests -q -m contract` (149 passed) 全绿。
- 黑盒：`npm --prefix src/frontend run test:e2e` (2 passed)。
- review：`review_general.md` verdict: PASS (Round 1)。
- AC 证据：见 `handoff.json`

### 结果摘要

- 个人收藏成功重构为收件箱、未读、已发三折叠树，未读角标精准呈现，列表按分类请求对应 folder_role 与过滤条件。
