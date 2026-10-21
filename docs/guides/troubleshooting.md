# 故障排查

## 启动即退出

|报错|原因 / 处理|
|---|---|
|`DatabaseConfigError: MAIL_CORE_DATABASE_URL ...`|未设置数据库 URL。compose 内由服务环境提供；直跑需自行导出。|
|`blob encryption keys required`|设置 `MAIL_CORE_BLOB_KEY_V1`，或用 `--data-dir` 让 mail-core 生成并持久化。|
|`Set MAIL_CORE_LOGIN_PASSWORD_HASH ...`|未配置登录密码（见 [security.md](security.md)）。|
|`MAIL_CORE_SECRET_KEY or SECRET_KEY is required ...`|未配置会话签名密钥（`openssl rand -hex 32`），或用 `--data-dir` 自动生成。|
|compose：`set POSTGRES_PASSWORD` 等|compose 的必填变量缺失，按 [deployment.md](deployment.md) 导出。|

## `/ready` 返回 503

响应体的 `reason` 字段指明原因：

- `database: <异常类型>` — PostgreSQL 不可达或认证失败。
- `schema_out_of_date` — 先执行 `alembic -c src/mail_core/db/alembic.ini upgrade head`（`python -m mail_core` 默认自动执行）。`/health` 的 `schema_head` 是代码期望的版本。
- `outbox_listener` — LISTEN 连接未建立，实时推送不可用；检查数据库连接数与权限。

## 账户不同步

1. 设置页查看账户 `sync_status`；worker 是否在运行（compose `worker` 服务或 `python -m mail_core` 内嵌 worker）。
2. 查询失败作业：`SELECT job_type, attempts, last_error FROM worker_jobs WHERE status='failed' ORDER BY updated_at DESC LIMIT 20;`（错误已脱敏）。
3. 429 / 限流会自动退避重排，不需要手动处理。
4. IMAP：确认服务器支持 993/TLS；明文 143 需在账户 `config` 中显式 `use_ssl: false`。

## 登录返回 429

失败次数过多，按 `Retry-After` 等待；阈值见 [security.md](security.md)。

## 忘记登录密码

系统以 PostgreSQL 数据库中的 `auth_credentials` 表为权威密码源。仅删除本地文件或修改环境变量不会覆盖数据库中已存在的密码记录。重置密码需操作数据库：

### 方法一：直接更新数据库密码哈希（推荐）

1. 生成新密码的 bcrypt 哈希：
    ```bash
    python3 -c "import bcrypt; print(bcrypt.hashpw(b'<新密码>', bcrypt.gensalt()).decode())"
    ```
2. 连接数据库并更新 `auth_credentials`：
    ```sql
    UPDATE auth_credentials
    SET login_password_hash = '<生成的bcrypt哈希>', updated_at = NOW()
    WHERE id = 'default';
    ```
3. 重启 mail-core 服务使新密码及内存缓存生效。

### 方法二：清空数据库凭据后重新引导

1. 停止 mail-core 服务。
2. 连接数据库删除旧凭据：
    ```sql
    DELETE FROM auth_credentials WHERE id = 'default';
    ```
3. 若使用了 `--data-dir`，同时删除 `<data-dir>/secrets/login-password.bcrypt`。
4. 导出新密码环境变量 `MAIL_CORE_LOGIN_PASSWORD`（或 `MAIL_CORE_LOGIN_PASSWORD_HASH`）；若未设置环境变量且使用 `--data-dir`，重启时会在 `<data-dir>/initial-password.txt` 重新生成初始随机密码。
5. 重启 mail-core 服务完成初次引导入库。

## 附件 / 原文读取报错

`blob content does not match its digest` 或 `InvalidTag` 表示 blob 文件被篡改或截断，或使用了错误的 blob 密钥版本；确认 `MAIL_CORE_BLOB_KEYS` 包含写入时的版本。
