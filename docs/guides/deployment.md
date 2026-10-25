# 部署

kkmail 只有一种服务端形态：mail-core API + worker + PostgreSQL，SPA 由 API 同源提供。

## Docker Compose

`docker-compose.mail-core.yml` 使用 Compose Specification，**不写**顶层 `version:`（该字段在现代 Docker Compose 中已废弃并被忽略）。

```bash
export POSTGRES_PASSWORD="$(openssl rand -hex 16)"
export MAIL_CORE_SECRET_KEY="$(openssl rand -hex 32)"
export MAIL_CORE_LOGIN_PASSWORD='<强密码>'            # 或 MAIL_CORE_LOGIN_PASSWORD_HASH（bcrypt）
export MAIL_CORE_BLOB_KEY_V1="$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"
export MAIL_CORE_BACKUP_KEY="$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')"

docker compose -f docker-compose.mail-core.yml up --build -d api worker   # 依赖会自动拉起 postgres 与 migrate
```

- 默认访问：`http://127.0.0.1:37281`。默认只把 API（主机 **37281**→容器 8000）和 PostgreSQL（主机 **5433**→容器 5432）发布到 `127.0.0.1`。若需通过本机 `.local` 主机名从局域网访问 API，设置 `MAIL_CORE_HOST_BIND=0.0.0.0` 后再启动 Compose，并访问 `http://<hostname>.local:37281`；这会监听主机 IPv4 接口。不要将端口直接暴露到公网，远程访问应放在 TLS 反向代理之后。文件里的 `imap` 服务是测试用 Dovecot 夹具（`127.0.0.1:1143`），部署时不要启动它（上面的命令只启动 `api` / `worker` 及其依赖）。
- 仓库不提供任何默认值。`POSTGRES_PASSWORD`、`MAIL_CORE_SECRET_KEY`、`MAIL_CORE_BLOB_KEY_V1`、`MAIL_CORE_BACKUP_KEY` 缺失时 compose 直接报错；登录密码（`MAIL_CORE_LOGIN_PASSWORD_HASH` 或 `MAIL_CORE_LOGIN_PASSWORD`）缺失时 API 进程拒绝启动。
- 可选：`MAIL_CORE_API_KEYS` 配置供脚本 / 集成使用的 Bearer Key（见 [docs/blueprint/conventions.md](../blueprint/conventions.md)）。
- `MAIL_CORE_BACKUP_KEY` 必须与 blob 密钥不同。密钥丢失 = 已归档邮件与凭据无法解密，请离线保存。
- 局域网 HTTP 部署继续可用，Compose 默认 `MAIL_CORE_COOKIE_SECURE=0`。HTTP 不加密会话 Cookie；同一网络中能够监听流量的设备可能读取 Cookie。仅在可信局域网使用 HTTP。敏感远程访问应经过 TLS 反向代理，并设置 `MAIL_CORE_COOKIE_SECURE=1`；启用 Secure Cookie 后，浏览器不会通过明文 HTTP 发送会话 Cookie。
- `migrate` 服务先执行 `alembic upgrade head`，`api` / `worker` 在其成功后启动（distributed API 已配置 `MAIL_CORE_SKIP_MIGRATIONS=1` 与 `MAIL_CORE_EMBEDDED_WORKER=0`，独立 worker 实例 ID 为 `distributed-worker-1`；若单进程运行可通过 `MAIL_CORE_SKIP_MIGRATIONS=0 MAIL_CORE_EMBEDDED_WORKER=1` 启动）；`/ready` 会在数据库不可达、schema 未到 head 或 LISTEN 未就绪时返回 503。

## 对外暴露

Google 网页 OAuth 需将 `MAIL_CORE_PUBLIC_ORIGIN` 设置为应用实际 HTTPS Origin（协议、域名及需要时的端口，不含路径或查询）。Compose 会将该值传入 API；修改后重新创建 API 容器。在 Google Cloud 的 Web OAuth 客户端登记 `<Origin>/api/accounts/oauth/callback/google`，与账户表单显示的回调 URI 完全一致，并启用 Gmail API、配置同意屏幕与测试用户。Client ID 和 Client Secret 在账户表单输入，服务端加密保存，不写入镜像或前端包。

未设置 Origin 时，网页 Google 跳转入口显示配置提示，其他 IMAP 与已有凭据连接仍可使用。Electron 使用自身动态 loopback 回调和桌面客户端，不要求此公网配置。`MAIL_CORE_ALLOW_LOOPBACK_OAUTH_ORIGIN` 仅供明确受信的本机测试使用，生产网页不应开启。

不要把 8000 端口直接暴露到公网。需要远程访问时放在 TLS 反向代理之后，并：

- 设置 `MAIL_CORE_COOKIE_SECURE=1`；
- 让 uvicorn 信任代理的 `X-Forwarded-For`（uvicorn 不读取环境变量，需在启动命令中传递命令行参数 `--forwarded-allow-ips=<代理地址>`；在 Docker Compose 中可通过覆盖 `api` 服务的 `command` 传入此参数），使登录限速按真实客户端地址生效；
- 数据目录、PostgreSQL 数据与 blob 根目录放在加密卷上（Docker volume 本身不加密）。

## 不使用 Docker

API 服务默认同源托管 React 前端页面（在 `src/frontend/dist/`）。非 Docker 部署时必须先构建 SPA：

```bash
# 1. 构建前端 SPA 产物
cd src/frontend
npm ci
npm run build
cd ../..

# 2. 准备 Python 依赖并启动
pip install -r requirements-mail-core.txt
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/kkmail
export PYTHONPATH=src
python -m mail_core --data-dir /var/lib/kkmail    # 迁移 + API + 内嵌 worker
```

若拆分独立进程部署，API 与 Worker 必须共享相同的数据库连接、密钥配置与 blob 路径（Worker 独立进程不会自动解析 `--data-dir`，需通过环境变量提供所需密钥与路径）：

```bash
# API 进程（提供 HTTP 服务与静态 SPA）
PYTHONPATH=src python -m mail_core --data-dir /var/lib/kkmail --no-worker

# Worker 进程（后台执行拉信同步与任务）
export PYTHONPATH=src
# 方式 A：通过环境变量加载共享密钥与存储目录
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/kkmail
export MAIL_CORE_BLOB_KEY_V1="$(cat /var/lib/kkmail/secrets/blob-v1.key)"
export MAIL_CORE_BLOB_ROOT=/var/lib/kkmail/blobs
export MAIL_CORE_BACKUP_KEY="$(cat /var/lib/kkmail/secrets/backup.key)"
export MAIL_CORE_BACKUP_DIR=/var/lib/kkmail/backups
python -m mail_core.worker.main

# 方式 B：通过 bootstrap 共享加载同一数据目录并启动 worker
export MAIL_CORE_DATABASE_URL=postgresql+psycopg://<user>:<password>@127.0.0.1:5432/kkmail
python -c "from mail_core.runtime.bootstrap import bootstrap_data_dir; bootstrap_data_dir('/var/lib/kkmail'); from mail_core.worker.main import run; run()"
```

`--data-dir` 下会生成并持久化会话 / blob / 备份密钥（`secrets/`，0600），未配置登录密码时生成一次性 `initial-password.txt`；已在环境变量中提供的值优先。完整变量列表见 [src/mail_core/README.md](../../src/mail_core/README.md)。

## Microsoft 账户登录

设置页选择 Microsoft 后，可使用浏览器登录或设备码登录。两种方式都由应用自动取得 Refresh Token，账号门户只提供 Client ID 与需要时的 Secret value。

浏览器登录：网页部署复用 `MAIL_CORE_PUBLIC_ORIGIN`，在自有 Entra 应用登记 Web 回调 `<Origin>/api/accounts/oauth/callback/microsoft`，填写匹配的 Secret value。Electron 选择移动和桌面应用，登记表单显示的 localhost 回调路径；微软对 localhost 忽略动态端口，但路径仍须匹配，此规则不适用于 127.0.0.1。

设备码登录：在 Entra Authentication 启用 Allow public client flows，回到设置页选择设备码方式。复制短验证码，打开界面给出的微软官方验证页，输入代码并登录，返回 kkmail 等待授权确认，再点击添加或保存。无需公网回调、固定本地端口或 Secret。

应用账号类型及租户须包含目标个人或组织账号。添加 Graph 委托 Mail.ReadWrite 与 User.Read，持续后台访问由应用自动申请。应用注册需要可用 Entra 租户与注册权限，企业可能要求管理员同意；并非每个个人微软账号都能自行创建应用。新增/编辑的帮助弹窗提供完整步骤与官方链接。
