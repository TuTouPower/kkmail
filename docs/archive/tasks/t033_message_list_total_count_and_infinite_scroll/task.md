---
tid: "t033"
slug: "message_list_total_count_and_infinite_scroll"
title: "修复邮件列表总数显示并支持触底自动加载"
status: "done"
branch: "t033_message_list_total_count_and_infinite_scroll"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "5b3f449ee1406d2f282be98f27571b05f90aa555"
depends_on: ""
conflicts_with: ""
note: ""
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. **头部总数计算**：普通视图取 `folderStatsQuery.data.total`（未读视图取 `unreadCount`，搜索视图取 `searchInfiniteQuery.data.pages[0].total`），未就绪前回退展示已渲染条数，杜绝单页条数误判为总数。
2. **触底自动无限滚动**：移除旧版手动“加载更多”按钮与统计文本，废弃稳定编号 `data-ui="ML14"`。引入 `IntersectionObserver`（提前 200px 视口触发）结合 `onScroll` 容错触底加载，通过 `loadingMore` 互斥锁防止重复触发。
3. **TDD 测试推进**：旧测试因依赖已废弃的手动加载按钮语义失效，予以完整删除；新建 4 组单元测试先红后绿覆盖 AC-001 ~ AC-005，全量单元测试、类型、生产构建、Lint 及 Playwright E2E 均全绿。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T05:18:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`src/frontend/src/components/MessageList.test.tsx`、全量前端测试 `npm test && npx tsc -b && npm run build && npm run lint`、后端 `pytest` 与 `run-mail-core-tests.sh` 全量通过
- 黑盒：Playwright UI 冒烟测试（`tests/e2e/smoke.spec.ts`、`tests/e2e/sidebar_tree.spec.ts`）、真实全栈端到端测试（`scripts/run_full_stack_e2e.py`）及桌面端打包产物冒烟（`npm run test:packaged`）全部通过
- review：`docs/tasks/t033_message_list_total_count_and_infinite_scroll/review_general.md` verdict: PASS (reviewed_scope: 1762bbdb6a83ffc4)
- AC 证据：见 `handoff.json`

### 结果摘要

- 修复邮件列表头部总数展示，对接服务端权威统计数据；
- 升级邮件列表为沉浸式触底自动无限滚动，废弃旧手动加载更多按钮并规范编号。

