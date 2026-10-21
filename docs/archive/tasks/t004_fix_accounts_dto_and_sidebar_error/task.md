---
tid: "t004"
slug: "fix_accounts_dto_and_sidebar_error"
title: "修复AccountDTO序列化异常与侧栏错误状态处理"
status: "done"
branch: "t004_fix_accounts_dto_and_sidebar_error"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "f915e78bcfc81767386f86b5e9f2448235f44fa7"
depends_on: ""
conflicts_with: ""
note: ""
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 后端修复：在 `src/mail_core/api/accounts.py` 中引入 `from dataclasses import asdict`，使用 `asdict(a)` 替换 3 处失效的 `dict(a.__dict__)`，彻底解决 `AccountDTO` 具有 `slots=True` 导致在序列化响应模型时触发 `AttributeError` 500 的问题。
2. 后端单测补齐：在 `tests/mail_core/test_accounts_api_unit.py` 中增加基于 Mock `AccountDTO`、`AccountPageDTO` 的真实结构序列化单测，覆盖 GET、POST、PATCH 路由层，无需外部数据库即可常态化拦截此类 DTO 序列化回归。
3. 前端错误态与重试：在 `src/frontend/src/components/Sidebar.tsx` 中使用 `errorMessage` 获取并透传真实错误信息（取代假定未登录的猜测文案），并在错误区块添加「重试」按钮触发 `accountsQuery.refetch()` 与 `groupsQuery.refetch()`。
4. 前端测试补齐：在 `src/frontend/src/components/Sidebar.test.tsx` 中补充接口 500 异常时的错误文本渲染与点击重试重新拉取数据的交互测试。
5. 集成测试真绿：显式注入测试数据库连接串，验证 `tests/mail_core/test_accounts_api_pg.py` 不再跳过且完整测试通过。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-22T07:37:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`pytest .repo_template/tests -q -m contract` (148 passed)、`pytest tests/mail_core -q` (194 passed)、`(cd src/frontend && npm test && npx tsc -b && npm run build)` (128 passed)、`(cd src/desktop && npm test)` 全绿。
- 黑盒：`npm --prefix src/frontend run test:e2e` (2 passed)。
- review：`review_general.md` verdict: PASS (Round 1)。
- AC 证据：见 `handoff.json`

### 结果摘要

- 修复了 `AccountDTO` 属性 `slots=True` 导致的 `GET /api/accounts` 500 异常，增加了无数据库依赖的标准路由层单测覆盖；优化了侧栏账户错误信息展示与一键重试交互。
