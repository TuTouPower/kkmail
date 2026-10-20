# 安全

## 认证

- **登录**：单一登录密码。使用 `MAIL_CORE_LOGIN_PASSWORD_HASH`（bcrypt，推荐）或 `MAIL_CORE_LOGIN_PASSWORD`（启动时哈希）；桌面 / `python -m mail_core --data-dir` 在未提供时生成随机初始密码写入 `secrets/initial-password.txt`，修改密码后删除。两者都没有时进程拒绝启动。
- **会话**：签名 Cookie（`MAIL_CORE_SECRET_KEY`，必填），`HttpOnly`，`SameSite=Lax`（`MAIL_CORE_COOKIE_SAMESITE`），有效期 `MAIL_CORE_SESSION_MAX_AGE`（默认 30 天）。经 HTTPS 访问时设置 `MAIL_CORE_COOKIE_SECURE=1`。
- **CSRF**：Cookie 会话下所有写请求必须带 `X-CSRF-Token`；前端拿不到令牌时不会发出写请求。
- **API Key**：`MAIL_CORE_API_KEYS`（逗号分隔或 JSON 列表），`Authorization: Bearer`；不接受查询串里的 key。
- **登录限速**：同一客户端地址在 `MAIL_CORE_LOGIN_WINDOW_S`（默认 300s）内失败 `MAIL_CORE_LOGIN_MAX_FAILURES`（默认 10）次后返回 429。按套接字对端地址计数，不信任 `X-Forwarded-For`；在反向代理后请用 `--proxy-headers --forwarded-allow-ips`。
- 修改密码：`POST /api/auth/password`（需当前密码）。

## 加密与密钥

| 数据 | 保护 |
| --- | --- |
| 原始邮件 / 附件 blob | 分块 AES-256-GCM（`KKMS`），内容寻址 SHA-256 读取时校验；无 magic 的数据拒绝读取 |
| 账户凭据（OAuth token / IMAP 密码） | `credential_secrets` 表，AES-256-GCM，密钥由 blob 密钥 HKDF 派生，AAD 绑定 ref |
| 备份包 | 独立的 `MAIL_CORE_BACKUP_KEY`（必须不同于 blob 密钥） |

- blob 密钥：`MAIL_CORE_BLOB_KEY_V1` 或 `MAIL_CORE_BLOB_KEYS`（JSON，多版本轮换）；没有密钥时拒绝启动，不存在开发默认值。
- `env:` 形式的凭据 ref 只读（运维管理），应用不会改写环境变量。
- 数据库密码只来自 `MAIL_CORE_DATABASE_URL`；仓库内不含任何默认凭据。

## 网络

- compose 与桌面版只监听 `127.0.0.1`。公网访问必须经 TLS 反向代理。
- OAuth token 端点限定为 Google / Microsoft 的 HTTPS 白名单。
- IMAP 默认 TLS（993），所有 provider 请求都有超时。

## 邮件内容

- HTML 正文经 DOMPurify 清洗后放入 sandbox iframe（`srcDoc`），默认不加载远程图片。
- 附件只能按 UUID 下载，响应带 `Content-Disposition: attachment` 与 `X-Content-Type-Options: nosniff`；路径形式的访问被拒绝。

## 日志

- 作业错误（`worker_jobs.last_error`、归档错误）经 `safe_error` / `redact` 处理：去掉 Bearer token、`token=`/`secret=`/`password=` 值、DSN 密码，不保存 provider 响应体。
- LISTEN/NOTIFY 日志只记录通道与字节数，不记录负载。
