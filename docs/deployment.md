# 部署

kkmail 只有一种服务端形态：mail-core API + worker + PostgreSQL，SPA 由 API 同源提供。

## Docker Compose

```bash
export POSTGRES_PASSWORD="$(openssl rand -hex 16)"
export MAIL_CORE_SECRET_KEY="$(openssl rand -hex 32)"
export MAIL_CORE_LOGIN_PASSWORD='<强密码>'            # 或 MAIL_CORE_LOGIN_PASSWORD_HASH（bcrypt）
export MAIL_CORE_BLOB_KEY_V1="$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"
export MAIL_CORE_BACKUP_KEY="$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"

docker compose -f docker-compose.mail-core.yml up --build -d api worker   # 依赖会自动拉起 postgres 与 migrate
```

- 访问：`http://127.0.0.1:8000`（**不是**旧 Flask `:5000` / 误写过的 `:5080`）。compose 只把 API（**8000**）和 PostgreSQL（主机 **5433**→容器 5432）发布到 `127.0.0.1`。文件里的 `imap` 服务是测试用 Dovecot 夹具（`127.0.0.1:1143`），部署时不要启动它（上面的命令只启动 `api` / `worker` 及其依赖）。
- 仓库不提供任何默认值。`POSTGRES_PASSWORD`、`MAIL_CORE_SECRET_KEY`、`MAIL_CORE_BLOB_KEY_V1`、`MAIL_CORE_BACKUP_KEY` 缺失时 compose 直接报错；登录密码（`MAIL_CORE_LOGIN_PASSWORD_HASH` 或 `MAIL_CORE_LOGIN_PASSWORD`）缺失时 API 进程拒绝启动。
- 可选：`MAIL_CORE_API_KEYS` 配置供脚本 / 集成使用的 Bearer Key（见 [api.md](api.md)）。
- `MAIL_CORE_BACKUP_KEY` 必须与 blob 密钥不同。密钥丢失 = 已归档邮件与凭据无法解密，请离线保存。
- `migrate` 服务先执行 `alembic upgrade head`，`api` / `worker` 在其成功后启动；`/ready` 会在数据库不可达、schema 未到 head 或 LISTEN 未就绪时返回 503。

## 对外暴露

不要把 8000 端口直接暴露到公网。需要远程访问时放在 TLS 反向代理之后，并：

- 设置 `MAIL_CORE_COOKIE_SECURE=1`；
- 让 uvicorn 信任代理的 `X-Forwarded-For`（compose 中给 `api` 加环境变量 `FORWARDED_ALLOW_IPS=<代理地址>`，或命令行 `--forwarded-allow-ips=<代理地址>`），使登录限速按真实客户端地址生效；
- 数据目录、PostgreSQL 数据与 blob 根目录放在加密卷上（Docker volume 本身不加密）。

## 不使用 Docker

```bash
pip install -r requirements-mail-core.txt
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/kkmail
python -m mail_core --data-dir /var/lib/kkmail    # 迁移 + API + 内嵌 worker
# 或拆分进程：python -m mail_core --no-worker  与  python -m mail_core.worker.main
```

`--data-dir` 下会生成并持久化会话 / blob / 备份密钥（`secrets/`，0600），未配置登录密码时生成一次性 `initial-password.txt`；已在环境变量中提供的值优先。完整变量列表见 [mail_core/README.md](../mail_core/README.md)。
