# 安全

## 认证

- **登录**：数据库模式以 `auth_credentials.login_password_hash` 为权威。`MAIL_CORE_LOGIN_PASSWORD_HASH`、`MAIL_CORE_LOGIN_PASSWORD` 与 `MAIL_CORE_PASSWORD_HASH_PATH` 仅用于首次引导，成功写入数据库后不再覆盖该值；无数据库模式使用进程内哈希。桌面 / `python -m mail_core --data-dir` 首次缺少密码时生成随机初始密码写入 `<data-dir>/initial-password.txt`，哈希存于 `secrets/login-password.bcrypt`；用户在设置页修改登录密码后删除明文文件。没有可用引导值时进程拒绝启动。
- **会话**：签名 Cookie（`MAIL_CORE_SECRET_KEY`，必填），`HttpOnly`，`SameSite=Lax`（`MAIL_CORE_COOKIE_SAMESITE`），有效期 `MAIL_CORE_SESSION_MAX_AGE`（默认 30 天）。经 HTTPS 访问时设置 `MAIL_CORE_COOKIE_SECURE=1`。
- **CSRF**：Cookie 会话下所有写请求必须带 `X-CSRF-Token`；前端拿不到令牌时不会发出写请求。
- **API Key**：`MAIL_CORE_API_KEYS`（逗号分隔或 JSON 列表），`Authorization: Bearer`；不接受查询串里的 key。
- **登录限速**：同一客户端地址在 `MAIL_CORE_LOGIN_WINDOW_S`（默认 300s）内失败 `MAIL_CORE_LOGIN_MAX_FAILURES`（默认 10）次后返回 429。按套接字对端地址计数，不信任 `X-Forwarded-For`；在反向代理后请在 uvicorn 启动命令中使用命令行参数 `--forwarded-allow-ips=<代理地址>` 只信任代理地址（uvicorn 不读取环境变量）。
- 修改密码：`POST /api/auth/password`（需当前密码，新密码至少 8 位）。
- `/health`、`/ready`、`/api/auth/login` 与 FastAPI 自带的 `/docs`、`/openapi.json` 不需要认证；后两者只暴露接口结构，不含数据。

## 授权模型（单用户 · UUID 即能力）

实例是**单用户**的：没有用户账户、角色或多租户隔离。Cookie Session 与 Bearer API Key 在实例内拥有同等完整访问权。

在该认证边界内，消息、附件、账户等资源的 **UUID 是能力（capability）**——持有有效会话/密钥且知道 UUID，即可调用对应 API。不要把这些 UUID 当作多租户下的「防 IDOR」标识来设计或审计；实例级认证是唯一边界。附件仍只允许按 UUID 下载（拒绝路径参数），目的是防路径穿越，不是按账号的行级 ACL。

## 加密与密钥

|数据|保护|
|---|---|
|原始邮件 / 附件 blob|分块 AES-256-GCM（`KKMS`），内容寻址 SHA-256 读取时校验；无 magic 的数据拒绝读取|
|账户凭据（OAuth token / IMAP 密码）|`credential_secrets` 表，AES-256-GCM，密钥由 blob 密钥 HKDF 派生，AAD 绑定 ref|
|备份包|独立的 `MAIL_CORE_BACKUP_KEY`（必须不同于 blob 密钥）|

- blob 密钥：`MAIL_CORE_BLOB_KEY_V1` 或 `MAIL_CORE_BLOB_KEYS`（JSON，多版本轮换）；没有密钥时拒绝启动，不存在开发默认值。
- `env:` 形式的凭据 ref 只读（运维管理），应用不会改写环境变量。
- 数据库密码只来自 `MAIL_CORE_DATABASE_URL`；仓库内不含任何默认凭据。

## 网络

- compose 与桌面版只监听 `127.0.0.1`。公网访问必须经 TLS 反向代理。
- OAuth token 端点限定为 Google / Microsoft 的 HTTPS 白名单。
- IMAP 默认 TLS（993）；`use_ssl=false` 只允许 `localhost` 或 loopback IP，并记录明文传输告警，非 loopback 明文配置会被拒绝。所有 provider 请求都有超时。

## 邮件内容

- HTML 正文只经 `src/frontend/src/lib/mailBody.ts` 的 `sanitizeMailHtml` → `buildMailSrcdoc` 进入 sandbox iframe（`srcDoc`）。实现与文档对齐点：
    - DOMPurify：`WHOLE_DOCUMENT: false`；`FORBID_TAGS` 含 `script` / `style` / `iframe` / `object` / `embed` / `form` / `input` / `button` / `textarea` / `select` / `base` / `meta` / `link`；`FORBID_ATTR` 含 `srcset` / `formaction` / `action`；`ALLOW_UNKNOWN_PROTOCOLS: false`。
    - 是否按 HTML 渲染只看后端 `body_type`（`isHtmlBody`），禁止内容嗅探与 `dangerouslySetInnerHTML`。
- iframe `sandbox="allow-popups allow-popups-to-escape-sandbox"`：邮件正文保持无脚本沙箱（**无** `allow-scripts`、**无** `allow-same-origin`），外链保留 `target="_blank"` 与 `rel="noopener noreferrer"`，在 Web SPA 模式下外部新窗口正常按浏览器安全策略运行，Electron 环境由主进程接管在系统浏览器中打开。
- 远程图片默认不加载（srcdoc CSP `img-src data: cid:`）；阅读器提供**一次性**允许加载（`loadRemoteImages`）。
- 附件只能按 UUID 下载，响应带 `Content-Disposition: attachment` 与 `X-Content-Type-Options: nosniff`；路径形式的访问被拒绝（见上文「UUID 即能力」）。

## 产品范围（安全相关）

- **浏览器扩展永久不做**（cancelled / wontfix）：不提供扩展、不维护 `/api/extension/*` 登录桥，也不再恢复旧 `browser-extension/` 代码路径。客户端仅为同源 SPA 与桌面 Electron。
- **已删除的 Flask 面**：旧 upstream 的上传暂存账号 / `outlook-upload-accounts` 明文密码列表、二次验证导出桥、Gunicorn `:5000` 管理面等均已不存在。勿再按历史 `docs/api.md` 或 Flask 段落实装/审计那些接口。

## 桌面 Electron

主进程（`src/desktop/main.js` + `src/desktop/hardening.js`）：

- `contextIsolation`、无 `nodeIntegration`、`sandbox`、禁用 `webviewTag`
- `will-attach-webview` 一律 `preventDefault`
- 权限请求与检查仅允许可信 `appOrigin` 的顶层页面写入 `clipboard-sanitized-write`；邮件 iframe、外部页面、子 frame 及其它权限（包括 `clipboard-read`、媒体设备、定位和通知）一律拒绝
- 会话级 Content-Security-Policy：`default-src 'self'`，禁止 `object`，`connect-src` 仅同源；邮件 HTML 仍由阅读器 iframe 的独立 CSP 约束（默认不加载远程图）
- 外链仅 `http(s):` / `mailto:` 交给系统浏览器；离开本地 origin 的导航被拦截

## 日志

- 作业错误（`worker_jobs.last_error`、归档错误）经 `safe_error` / `redact` 处理：去掉 Bearer token、`token=`/`secret=`/`password=` 值、DSN 密码，不保存 provider 响应体。
- LISTEN/NOTIFY 日志只记录通道与字节数，不记录负载。

## 防火墙与反向代理

mail-core / compose **只监听 `127.0.0.1`**（API 默认 **8000**，不是旧 Flask **5000**）。

- **不要**在防火墙上对公网开放 `8000/tcp`（或历史文档里的 `5000/tcp`）。
- 需要远程访问时：只放行 **80/443**，由 TLS 反向代理转到本机 `127.0.0.1:8000`，并设置 `MAIL_CORE_COOKIE_SECURE=1`；因 uvicorn 不读取环境变量，需在启动命令中传递命令行参数 `--forwarded-allow-ips=<代理地址>`（见 [deployment.md](deployment.md)）。
- 桌面版同样只绑 loopback；不要把 sidecar 端口映射到局域网。

## 备份（勿用裸 `cp`）

不要用 `cp` 复制正在运行的 PostgreSQL 数据目录或历史 SQLite 路径当备份。使用密封备份包，执行说明与 Runbook 统一见 [upgrade.md](upgrade.md)。

备份密钥（`MAIL_CORE_BACKUP_KEY`）必须与 blob 密钥不同，并离线保存。恢复演练见 `scripts/mail-core-backup-restore-drill.sh`。
