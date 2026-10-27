# Intensive Review — 视角1 安全与开源隐私泄露排查 (Security & Privacy)

## 视角摘要

外部输入、认证授权、会话管理、数据脱敏、开源仓历史泄露排查、网络防护与安全响应头。
目标状态：当前仓库已探测为公开开源仓 (`TuTouPower/kkmail` isPrivate=false)。

## Findings

- [Critical][100] [REDACTED_HISTORICAL_LOCATOR] — 历史 Commit 泄露真实有效 Outlook 邮箱、明文密码与 OAuth Refresh Token — 在历史提交 `[REDACTED_HISTORICAL_COMMIT]` 中，`outlook_mail_reader.py` 硬编码了真实邮箱 `redacted_outlook@example.com`、明文密码 `REDACTED_PASSWORD`、ClientID `00000000-0000-0000-0000-000000000000` 以及完整的生产 OAuth Refresh Token。虽然当前工作区该文件已删除，但公开开源仓通过 `git show [REDACTED_HISTORICAL_LOCATOR]` 任何人均可检索读取，存在账号被接管风险 — 立即废除该微软账户凭据与 OAuth 授权，并在仓库中使用 git-filter-repo 彻底重写提交历史清除凭据。
- [High][100] [REDACTED_HISTORICAL_LOCATOR] — 历史 Commit 泄露真实手机号及个人真实邮箱 PII 隐私 — 历史提交 `[REDACTED_HISTORICAL_COMMIT]` 的 `demoAccounts` 中包含国内真实手机号邮箱 `redacted_mobile@example.com` 以及真实个人 Gmail/Outlook 账号。开源后造成直接的实名隐私关联泄露 — 使用 git-filter-repo 对历史提交执行脱敏打码。
- [High][100] scripts/migrate_from_legacy_db.py:68-69 — 数据库迁移脚本硬编码默认 Fallback 解密密钥 — 脚本中使用 `legacy_secret = os.environ.get("LEGACY_SECRET_KEY", "[REDACTED_KEY]")`。任何旧版 SQLite 数据库若使用默认 key 或迁移未传参，其保存的所有账号密码、OAuth token 均可被该硬编码 256 位密钥批量解密 — 移除硬编码默认密钥，若环境变量未提供直接中断退出。
- [High][95] src/mail_core/api/app.py:59-76 — Web/Docker 部署模式全局缺失关键安全响应头 — FastAPI 仅在 Electron 桌面端外壳附加了 CSP，当作为独立 Web 或 Docker 容器部署时，HTTP 响应完全缺失 `Content-Security-Policy`、`X-Frame-Options`（存在点击劫持风险）、`X-Content-Type-Options: nosniff` 以及 `Strict-Transport-Security` — 在 FastAPI 顶层中间件统一注入基础安全响应头。
- [High][95] src/mail_core/api/app.py:79-94 — 缺省反向代理配置导致登录失败限流产生全局拒绝服务 DoS — `__main__.py` 启动 uvicorn 未启用 `--proxy-headers` 或 `forwarded_allow_ips`。在 Docker 容器或反代部署下，所有外部访问的 `request.client.host` 均为网关 IP；任意未授权用户输入 10 次错误密码触发限流后，导致所有合法用户均无法登录（返回 429） — 提供反向代理配置开关并在 uvicorn 启动参数中安全装配 `proxy_headers` 与 `forwarded_allow_ips`。
- [Medium][95] src/mail_core/security/auth.py:73-80 — 会话 Cookie 默认未启用 Secure 属性 — `docker-compose.mail-core.yml:61` 默认设定 `MAIL_CORE_COOKIE_SECURE=0`，在缺少该环境变量且由反向代理转发至容器内部时，Cookie 未打上 `Secure` 标记，局域网中易受 SSL 剥离窃取 — 检测 `X-Forwarded-Proto: https` 自动判定，并在生产部署指南中强制要求配置。
- [Medium][90] src/mail_core/security/redact.py:14-23 — 日志脱敏正则未覆盖 HTTP Basic Auth 与通用代理协议 URL — 当前脱敏正则仅匹配 `Bearer` 和 `postgres://`，若日志中包含 `Authorization: Basic <base64>` 或带账号密码的 HTTP/SOCKS 代理连接串，密码将明文输出至日志 — 扩展脱敏正则为通用 URL 与认证格式。
- [Medium][90] src/mail_core/runtime/bootstrap.py:81 — 初始生成的登录密码以明文形式永久滞留磁盘 — `bootstrap_data_dir()` 生成的 `initial-password.txt` 虽为 0600 权限，但无任何自毁或过期清理机制，主机数据目录长期滞留明文最高权限凭据 — 建议首次登录成功或重置密码后自动清除该明文文件。
- [Medium][85] src/mail_core/providers/factory.py:72-80 — IMAP 提供商未对内网地址进行校验存在 SSRF 风险 — 用户通过 API 添加 IMAP 账号时可指定任意内网 IP（如 127.0.0.1、10.0.0.0/8），后台 Worker 发起 TCP 连接并发送明文字符串，可用于探测内网端口或进行跨协议攻击 — 增加 Host 校验，禁止连接内网保留网段。
- [Low][100] [REDACTED_HISTORICAL_LOCATOR] — 历史 Commit 包含开发者个人 Telegram 账号与私有邮箱 — 提交 `[REDACTED_HISTORICAL_COMMIT]` 包含 `https://t.me/example` 与 `redacted_developer@example.com`，公开仓库暴露个人通讯录 — 建议重写该历史提交以保护开发者隐私。
- [Low][90] src/mail_core/security/auth.py:233-235 — Session Epoch 异常降级容错可能导致历史已吊销会话短暂生效 — 校验 Session 时若遭遇瞬时数据库异常，直接 `except Exception: return _session_epoch`（内存默认值 1），导致数据库中已废弃的 epoch=1 会话在降级期间误通过校验 — 应坚持 Fail-Closed 原则，数据库异常时拒绝会话认证。
- [Low][85] src/frontend/src/lib/diagnostics.ts:44-101 — 前端挂载诊断对象且 context 字段未脱敏 — `window.__kkmail_diagnostics` 挂载在全局 window，且 `context` 仅执行 JSON.stringify 未经过敏感词过滤 — 对 context 递归脱敏，并在生产构建时避免暴露全局对象。
- [Low][80] src/desktop/paths.js:20-29 — 桌面端外链过滤器未限制 http 本地回环地址 — `isAllowedExternalUrl` 允许 `http:` 且未过滤 `http://127.0.0.1`，点击外链可能触发系统浏览器请求本地敏感服务 — 限制外部链接必须为 `https:` 或添加外部跳转确认。
