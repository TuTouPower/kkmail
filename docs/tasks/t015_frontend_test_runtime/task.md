---
tid: "t015"
slug: "frontend_test_runtime"
title: "恢复前端测试门禁并固定浏览器存储测试环境"
status: "backlog"
branch: ""
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: "t006,t008,t009,t010,t011,t012,t013,t014,t016,t017,t018,t019,t020,t021,t022,t023"
note: "本会话批准测试增强；本地复用专用 PG 容器、每轮独立测试库；仅创建 backlog"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

来源为本会话 2026-10-22 实测：30 个测试文件，4 个失败；34 failed / 112 passed。仅记录症状，不伪造根因结论。

### 2026-10-22 主分支执行

- 用户明确要求直接在 main 分支按顺序执行 t013–t023，每完成一个 task 独立 commit。
- 定位存储不可用根因：Node 24 环境下 Vitest jsdom 存储初始化与 Zustand persist 导入时序冲突；建立 `src/frontend/src/test/test_setup.ts`，在任何 store 模块导入前确保 jsdom 提供的 localStorage 与 sessionStorage 正确挂载到 globalThis。
- 完善用例间状态隔离：在 setup/cleanup 中重置 Zustand store 到初始状态、清理 localStorage/sessionStorage、清空 TanStack QueryClient、重置 CSRF 内存 token、清理挂载 DOM 根节点、恢复全局 fetch/timers/window 事件监听器。
- 补齐行为与持久化测试：新增 `src/frontend/src/test/persistence.test.ts` 验证偏好持久化、store 重新加载、旧偏好向前兼容、Quota 异常与 Hydration 错误路径；新增 `src/frontend/src/test/test_runtime.test.tsx` 连续 2 轮用例隔离验证。
- 升级构建与门禁：package.json 引入 `@vitest/coverage-v8`，`vite.config.ts` 配置 jsdom 环境及覆盖率输出目录；`tsconfig.app.json` 补全 `DOM.Iterable` 支持 NodeList 迭代展开；配置 `.oxlintrc.json` 规则使 `npm run lint` 零警告通过。
- 门禁全通：`npm test` 34 passed / 168 passed（原 34 项失败全部修复）；`npm run test:coverage` 报告生成成功；`tsc -b && vite build` 生产打包成功；`test:e2e` 冒烟全过。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

- 无未解决 finding，单人审查已 PASS（见 `review_general.md`）。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：前端测试门禁与存储运行环境修复完成，所有行为 AC 均满足。
- 测试：`npm test` 34 passed / 168 passed；`tsc -b` 零类型错误；`npm run build` 成功。
- 黑盒：`npm --prefix src/frontend run test:e2e` 3 passed。
- review：`review_general.md` 结论 PASS。
- AC 证据：`persistence.test.ts`、`test_runtime.test.tsx`、`npm test` 与 `test:coverage` 终端输出。

### 结果摘要

修复了 Node 24 下前端测试 jsdom 存储未注入导致 34 项测试失败的问题；固定了前置初始化与后置清理机制，实现各测试用例间严格的状态隔离与覆盖率收集能力。
