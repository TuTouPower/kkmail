---
tid: "t017"
slug: "full_stack_e2e"
title: "建立浏览器到真实后端数据库与 Worker 的端到端测试"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: "t012,t015,t016"
conflicts_with: "t006,t008,t009,t010,t011,t012,t013,t014,t015,t016,t018,t019,t020,t021,t022,t023"
note: "本会话批准测试增强；本地复用专用 PG 容器、每轮独立测试库；仅创建 backlog"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

2026-10-22 核实 tests/e2e/smoke.spec.ts、stubApi.ts、playwright.config.ts；当前 E2E 未在本轮执行，评估只确认其模拟边界。

### 2026-10-22 主分支执行

- 用户明确要求直接在 main 分支按顺序执行 t013–t023，每完成一个 task 独立 commit。
- 架构分层：
    - 保留轻量快速 UI 冒烟测试（`tests/e2e/smoke.spec.ts`，基于 Playwright stubApi，运行仅 4 秒）；
    - 新建真实全栈端到端测试（`tests/e2e/full_stack.spec.ts`，涵盖真实 FastAPI、PostgreSQL、Worker、Dovecot IMAP 与生产 SPA 静态托管）。
- 编写生命周期控制器 `scripts/run_full_stack_e2e.py`：
    - 启动前核对专用测试 IMAP 容器与测试 PostgreSQL 实例；
    - 动态分配一次性测试库 `kkmail_e2e_<uuid>`，执行 Alembic head 迁移；
    - 设置 `KKMAIL_FRONTEND_DIST`，FastAPI 生产同源挂载 SPA；
    - 启动独立 API 进程与 Worker 进程，等待 `/health` 健康就绪；
    - 动态分配未占用端口，启动 Playwright 并执行 `full_stack.spec.ts`；
    - 运行后优雅终止进程并安全销毁测试库，失败保留截图与日志在 `.scratch/`。
- 修复测试发现的根因问题：
    - 数据库 URL 特殊字符（如包含 `%`）必须经由 `URL.create` 规范化渲染，消除 psycopg percent-decode 异常对 LISTEN 线程的影响；
    - API 认证环境变量对齐 `MAIL_CORE_LOGIN_PASSWORD`，Session Cookie 对齐 `kkmail_mc_session`；
    - 前端邮件项 class 对齐 `.message-row`。
- 验收结果：`python3 scripts/run_full_stack_e2e.py` 3 项测试全通（15.8s）；`npm --prefix src/frontend run test:e2e` 快速冒烟 3 项全通。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

- 已修：PostgreSQL DSN URL 编码修正，防止含有保留符号触发 ProgrammingError；
- 已修：Playwright 快速冒烟与全栈脚本测试目标隔离；
- 双人审查（code + test）结论均 PASS。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全栈真实端到端自动化测试门禁建立完成，全行为 AC 均满足。
- 测试：`python3 scripts/run_full_stack_e2e.py` 3 passed；`npm --prefix src/frontend run test:e2e` 3 passed。
- 黑盒：浏览器中成功登录、获取 Cookie、CSRF 校验、添加账户后真实 Worker 自动同步落库并渲染邮件列表、XSS 防护过滤、双页面 SSE 实时协同。
- review：`review_code.md` PASS，`review_test.md` PASS。
- AC 证据：`scripts/run_full_stack_e2e.py` 与 `tests/e2e/full_stack.spec.ts` 终端实测输出。

### 结果摘要

建立了基于真实环境（FastAPI、Worker、PostgreSQL、Dovecot、生产 SPA）的端到端自动化测试流水线与用例套件，验证了真实 Cookie/CSRF 认证、多会话失效、添加账号后台自动同步、邮件详情阅读与 XSS 过滤、双页面并发 SSE 实时推送等关键链路，并在测试后自动销毁数据库与后台进程。
