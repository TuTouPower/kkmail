# Bundle Review — dir:tests/e2e

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 2 allowlisted tracked files

## Findings

- [Low][100] tests/e2e/stubApi.ts:76-L94 — E2E 登录 stub 缺少 CSRF token，测试未发现后续写操作失败 — 证据：/me 与 login body 未提供 client 读取的 csrf_token；打开邮件会触发标记已读，但 E2E 只断言详情渲染。相关 spec 路径还指向不存在的 src/frontend/e2e/。 — 依据：src/frontend/src/api/client.ts:240 从登录 body 读取 token；docs/specs/auth_and_session.md:45、docs/specs/inbox_ui_and_search.md:50 的 E2E 路径过时。 — 修复：stub 补齐 token 契约，断言写请求携带 CSRF；更正 spec 路径并覆盖登出。

## Files examined

- tests/e2e/smoke.spec.ts
- tests/e2e/stubApi.ts
