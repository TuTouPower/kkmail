# mail-core

kkmail 后端核心服务。规范参考：[`docs/blueprint/architecture.md`](../../docs/blueprint/architecture.md)，部署指南：[`docs/guides/deployment.md`](../../docs/guides/deployment.md)。

## 运行

```bash
pip install -r requirements-dev.txt
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/<db>
python -m mail_core --data-dir ./.kkmail-data
```

`python -m mail_core` 会自动执行数据库迁移，在同进程中启动 Worker 线程，并通过 uvicorn 启动 REST API。

|参数选项|对应环境变量|默认值 / 行为说明|
|---|---|---|
|`--host`|`MAIL_CORE_HOST`|`127.0.0.1`|
|`--port`|`MAIL_CORE_PORT`|`8000`|
|`--data-dir`|`MAIL_CORE_DATA_DIR`|未设置。设置时，将在该目录下自动自举缺失的安装密钥与存储路径。|
|`--no-worker`|`MAIL_CORE_EMBEDDED_WORKER=0`|默认启用内嵌 Worker。如需单独运行：`python -m mail_core.worker.main`。|
|`--skip-migrations`|`MAIL_CORE_SKIP_MIGRATIONS=1`|默认在启动时自动执行数据库迁移。|
|`--proxy-headers`|`MAIL_CORE_PROXY_HEADERS`|请求代理标头处理。需要配合 `--forwarded-allow-ips` 或 `MAIL_CORE_FORWARDED_ALLOW_IPS`；若未配置受信任主机，则记录警告并禁用转发标头。|
|`--forwarded-allow-ips`|`MAIL_CORE_FORWARDED_ALLOW_IPS`|未设置。以逗号分隔的受信任代理 IP/CIDR 清单；为这些对端启用 `X-Forwarded-*` 解析。|

当 `--data-dir` 自举需要创建登录凭据时，会将随机初始密码写入 `<data-dir>/initial-password.txt`，并将其 bcrypt 哈希写入 `<data-dir>/secrets/login-password.bcrypt`（权限均为 `0600`）。明文密码文件保留至用户在设置中修改登录密码后自动删除。配置数据库后，自举完成后以 `auth_credentials.login_password_hash` 为权威凭据。

## 环境配置

|环境变量|用途说明|
|---|---|
|`MAIL_CORE_DATABASE_URL`|**必填。** 无默认值。|
|`MAIL_CORE_SECRET_KEY`|会话签名密钥。不使用 `--data-dir` 时必填；使用 data-dir 自举时会自动生成并持久化。|
|`MAIL_CORE_LOGIN_PASSWORD_HASH`, `MAIL_CORE_LOGIN_PASSWORD`, `MAIL_CORE_PASSWORD_HASH_PATH`|登录自举凭据来源。入库后以数据库凭据行为权威。|
|`MAIL_CORE_API_KEYS`|集成调用的 Bearer Token。|
|`MAIL_CORE_LOG_LEVEL`|根日志级别，默认为 `INFO`。非法值将记录警告并回退到 `INFO`。|
|`MAIL_CORE_COOKIE_SECURE`, `MAIL_CORE_COOKIE_SAMESITE`, `MAIL_CORE_SESSION_MAX_AGE`|会话 Cookie 控制：未设置时 secure 跟随 HTTPS，SameSite 默认为 `lax`，max-age 默认为 30 天。|
|`MAIL_CORE_LOGIN_MAX_FAILURES`, `MAIL_CORE_LOGIN_WINDOW_S`|登录失败速率限制，默认 300 秒内最多失败 10 次。|
|`MAIL_CORE_SSE_MAX_CONNECTIONS`|单进程最大并发 SSE 流连接数，默认为 128。|
|`MAIL_CORE_FORWARDED_ALLOW_IPS`|受信任代理 IP/CIDR；未设置时禁用代理标头中间件。|
|`MAIL_CORE_PUBLIC_ORIGIN`, `MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN`|Microsoft Web OAuth Origin 与本地测试 Loopback HTTP 许可；默认关闭。|
|`MAIL_CORE_ALLOW_PRIVATE_HOSTS`|允许 IMAP 连接到私有/回环主机；默认关闭。|
|`KKMAIL_SIDECAR`, `KKMAIL_INSTANCE_TOKEN`|仅限桌面端运行标记与 `/health` 握手令牌；Web 部署请勿配置。|
|`KKMAIL_FRONTEND_DIST`|同源托管挂载在 `/` 的前端 SPA 产物目录。|
|`MAIL_CORE_BLOB_KEY_V1`, `MAIL_CORE_BLOB_KEYS`, `MAIL_CORE_BLOB_KEY_VERSION`, `MAIL_CORE_BLOB_ACTIVE_VERSION`|Blob 与凭据密文密钥环。提供单个 base64 32字节密钥或版本映射 JSON；活跃版本默认为已配置的最高版本。|
|`MAIL_CORE_BLOB_ROOT`, `MAIL_CORE_BLOB_SOFT_BYTES`, `MAIL_CORE_BLOB_HARD_BYTES`|Blob 存储根路径与软/硬配额上限。无 data-dir 时根路径默认为 `[REDACTED]mail-core-blobs`。|
|`MAIL_CORE_BACKUP_KEY`, `MAIL_CORE_BACKUP_KEYS`, `MAIL_CORE_BACKUP_KEY_VERSION`|备份加密密钥环，密钥必须不同于 Blob 密钥。活跃版本默认为已配置的最高版本。|
|`MAIL_CORE_BACKUP_DIR`|备份产物输出目录；默认为 `<data-dir>/backups` 或 `[REDACTED]mail-core-backup`。|
|`MAIL_CORE_DB_POOL_SIZE`, `MAIL_CORE_DB_MAX_OVERFLOW`, `MAIL_CORE_DB_POOL_TIMEOUT`, `MAIL_CORE_DB_POOL_RECYCLE`|SQLAlchemy 连接池设置。默认值分别为：10 / 10 / 30秒 / 1800秒。|
|`MAIL_CORE_EMBEDDED_WORKER`, `MAIL_CORE_WORKER_ID`, `MAIL_CORE_WORKER_POLL_S`, `MAIL_CORE_WORKER_MAX_IDLE_S`|内嵌 Worker 与轮询控制。默认启用内嵌，轮询间隔 2 秒，最大空闲 `max(poll, 10)`；未配置时自动生成 Worker ID。|
|`MAIL_CORE_RECLAIM_STALE_SECONDS`, `MAIL_CORE_JOB_MAX_ATTEMPTS`, `MAIL_CORE_ARCHIVE_BATCH`|Worker 回收、重试与批次上限。默认：300秒 / 最多 8 次重试 / 每批归档 20 封邮件。|
|`MAIL_CORE_PG_CONNECT_TIMEOUT`, `MAIL_CORE_PG_DUMP_TIMEOUT`, `MAIL_CORE_PG_RESTORE_TIMEOUT`|备份 PostgreSQL 连接、转储与恢复超时设置。默认分别为：10秒 / 300秒 / 300秒。|
|`MAIL_CORE_PROXY_HEADERS`|启用代理标头处理；需要配置受信任的 `MAIL_CORE_FORWARDED_ALLOW_IPS`。|

## 目录分层

|目录路径|职责说明|
|---|---|
|`api/`|FastAPI 路由组装入口（assembly entry point）：`app.py` 构建应用并挂载路由；包含 `auth_routes`、`accounts`、`mail`、`sse` 与 `oauth_routes`。路由仅允许调用 application 层。|
|`mail/application/`|读取模型、搜索、状态变更、远端操作与附件处理。|
|`mail/domain/`, `mail/storage/`|领域枚举、归档状态机、ORM 数据实体与文件夹聚合统计。|
|`accounts/`|账户、分组、设置与凭据安全存储（数据库加密、只读 `env:`、`keyring:`）。|
|`sync/`|租约与 fencing 锁、后台任务、元数据与增量同步引擎。|
|`providers/`|IMAP 与 Graph 提供商协议适配器、Microsoft OAuth 与出站写回。|
|`worker/`|后台任务轮询循环与执行处理器。|
|`blobs/`|KKMS 流式 AEAD 加密存储、归档调度器、GC 垃圾回收与密钥轮换。|
|`backup/`|KKBK 备份包打包与恢复引擎。|
|`realtime/`|Outbox 分发器与 PostgreSQL LISTEN/NOTIFY 监听。|
|`security/`|鉴权认证、脱敏与登录失败速率限制。|
|`runtime/`|`--data-dir` 密钥与运行环境自举。|

## 测试

```bash
export MAIL_CORE_DATABASE_URL=...   # 测试专用数据库
scripts/run-mail-core-tests.sh      # 迁移 + pytest 门禁；数据库门控测试不允许跳过
```
