# t017 代码审查

## 范围与执行方式

审查 t017 全栈端到端测试链路与控制入口实现：

- `scripts/run_full_stack_e2e.py`: 真实环境编排（PG 分配、迁移、FastAPI 同源托管 SPA、Worker、健康轮询、Playwright 执行与优雅销毁）
- `tests/e2e/full_stack.spec.ts`: 覆盖真实认证、Cookie/CSRF、多会话失效、添加账号、Worker 自动同步、邮件详情阅读、XSS 防护及 SSE 跨页协同
- `src/frontend/playwright.config.ts`: 支持 `process.env.BASE_URL` 真实环境接入，配置 `retain-on-failure` 追踪与截图
- `src/frontend/scripts/run_e2e.mjs`: 快速 UI 冒烟测试目标隔离

## Finding 处置

- 已修 important: 数据库 URL 生成与特殊字符编码。使用 SQLAlchemy `URL.create` 生成符合 RFC 规范的连接串，防止包含 `%` 等特殊符号的密码触发 psycopg percent-decode 异常导致 LISTEN 线程故障。
- 已修 important: 环境变量对齐。API 服务认证密码对齐 `MAIL_CORE_LOGIN_PASSWORD`，Session Cookie 对齐 `kkmail_mc_session`。

## 结论

PASS。无未解决 critical 或 important 问题。
