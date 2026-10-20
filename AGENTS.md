# kkmail 编码代理指南

## 项目概况

- 仓库 `TuTouPower/kkmail`（fork 自 assast/outlookEmail，后端已整体替换）。
- 后端唯一实现：`mail_core/`（FastAPI + PostgreSQL + worker）。前端唯一实现：`frontend/`（React SPA，由 mail-core 同源提供）。桌面：`desktop/`（Electron + 本地 PostgreSQL + `python -m mail_core` sidecar）。
- 产品范围不含发信、联系人、系统通知；不要新增这些入口。
- **浏览器扩展永久 out of scope（wontfix）**：不要恢复 `browser-extension/`、`/api/extension/*` 或任何扩展交付计划。

## 目录

| 路径 | 说明 |
| --- | --- |
| `mail_core/` | 后端；模块分层见 `mail_core/README.md` |
| `mail_core/db/alembic/` | 迁移；模型改动必须带迁移 |
| `frontend/src/api/` | `client.ts`（唯一 HTTP 传输：Cookie + CSRF + 超时）、`mailCore.ts`（邮件端点）、`queries.ts`（React Query 缓存） |
| `desktop/` | Electron 主进程、`postgresManager.js` |
| `tests/mail_core/` | pytest（大部分需要 PostgreSQL） |
| `docs/` | 架构、部署、安全 |

## 开发与测试

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://<user>:<pass>@127.0.0.1:5433/<test-db>
scripts/run-mail-core-tests.sh             # alembic upgrade + pytest tests（DB 用例不允许 skip）

cd frontend
npm ci
npm run lint                               # oxlint --deny-warnings
npx tsc -b
npm test                                   # vitest（含 jsdom 组件测试）
npm run build
npm run dev                                # 代理 /api → 127.0.0.1:8000（MAIL_CORE_PROXY_TARGET 可改）

cd ../desktop && npm ci && npm test
```

提交前：pytest 全量 + 前端 lint / tsc / vitest / build。

## 约定

- **邮件 HTML** 只能经 `frontend/src/lib/mailBody.ts`（DOMPurify + sandbox iframe `srcDoc`）；是否 HTML 只看 `body_type`；禁止 `dangerouslySetInnerHTML`。
- **消息标识** = mail-core 消息 UUID（`lib/mailKey.ts`）；账户用 UUID（`accountId`），不要用邮箱地址当 ID。
- **单用户 · UUID 即能力**：实例无多租户/行级用户 ACL。在已认证的 Session / API Key 边界内，知道资源 UUID 即可访问该资源；不要按「防 IDOR 的多租户 ID」来实现或评审。详见 `docs/security.md` 与 `docs/mail-core-architecture.md` §11.4。
- **HTTP** 一律走 `api/client.ts` 的 `apiRequest` / `postJson`：写请求自动带 `X-CSRF-Token`，拿不到令牌时直接失败。
- **API 契约**：每个路由声明 `response_model`；错误用 `HTTPException`（`{"detail": ...}`）；路由只调用 `mail_core.mail.application` / `mail_core.accounts`，不直接访问 ORM 或 sync 内部。
- **密钥**：不写默认值、不写示例密钥；缺失时拒绝启动。凭据只经 `CredentialStore`（默认数据库加密存储）；日志 / `last_error` 必须经 `mail_core.security.redact`。
- **测试**不得连接非一次性数据库；新的 DB 用例沿用 `skipif(not MAIL_CORE_DATABASE_URL)` 标记。`scripts/run-mail-core-tests.sh` 会设置 `MAIL_CORE_REQUIRE_DB=1`，没有数据库就失败而不是跳过。
- **表单字段**要有 `id` 或 `name`；密码框带 `autoComplete` 且在 `<form>` 内。
- **移动端断点 760px**：与 `lib/viewport.ts` 和 `design-system/tokens.css` 保持一致；导航走 store 的 `setView` / `openSmartView`。
- **UI 文案中文**；图标按钮要有 `title` 与 `aria-label`；破坏性操作先 `confirmAction`。

## 提交规范

Conventional Commits，英文主题行，可带 scope（`mail-core`、`api`、`frontend`、`desktop`、`docs`、`ci`、`security`），正文可用中文。每个提交可构建、测试通过。
