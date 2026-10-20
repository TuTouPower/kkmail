# mail-core 桌面 PostgreSQL 子进程

架构依据：`docs/mail-core-architecture.md` §4.3 / M6。

## 数据目录（安装目录之外）

Electron 使用 `app.getPath('userData')/mail-core-data/`：

| 子路径 | 用途 |
|---|---|
| `pgdata/` | PostgreSQL 数据目录 |
| `blobs/` | 内容寻址 MIME blob |
| `backups/` | 备份包输出 |
| `README-DO-NOT-DELETE.txt` | 提醒卸载默认不得删除 |

**卸载默认不得删除**该目录；清除需用户显式「清除本地邮件数据」。

## API（`desktop/postgresManager.js`）

```js
const { PostgresManager } = require('./postgresManager')
const pg = new PostgresManager({ app }) // Electron app
pg.ensureDirs()
pg.status()   // { stub, running, dataRoot, port, binaries }
pg.start()    // uses vendor/PATH binaries when present; else stub:true
pg.stop()
```

## 二进制（vendor 打包路径）

解析顺序：

1. `KKMAIL_PG_BIN` / `PostgresManager({ pgBinDir })`
2. `desktop/vendor/pgsql/bin`（官方二进制；**不进 git**）
3. 系统 `PATH` 上的 `initdb` / `pg_ctl`

获取开发用二进制：

```bash
# Linux
./scripts/fetch-pg-binaries.sh
# macOS/Windows: download-at-build（见 desktop/vendor/README.md）
# 或手动解压到 desktop/vendor/pgsql/bin/
```

详见 [`desktop/vendor/README.md`](../desktop/vendor/README.md)。

无二进制时：`start()` 创建数据目录并返回 `{ stub: true }`，`main.js` 将其视为致命错误并提示（mail-core 是唯一后端，没有无 PG 的回退）。

## 启动顺序

1. `PostgresManager.start()`：loopback 集群，`scram-sha-256`，每次安装随机密码（`secrets/pg-password`，0600），首次 `createdb kkmail_mail`。
2. 启动 `python -m mail_core --data-dir <dataRoot>`（打包后为 sidecar `kkmail-backend`）：生成/加载 `secrets/` 下 session/blob/backup 密钥，`alembic upgrade head`，API + 内嵌 worker 绑定 `127.0.0.1`。
3. `/health` 就绪后打开窗口；首次运行显示一次随机初始登录密码，修改密码后 `initial-password.txt` 被删除。

## 与 Docker 的关系

桌面与 Docker **同一 PG 主版本目标、同一 Alembic schema**。开发可用 `docker-compose.mail-core.yml` / `docker run postgres:16`；桌面路径用本地子进程。

## Packaging scaffold (electron-builder)

```bash
cd desktop
npm ci
# optional: ../scripts/fetch-pg-binaries.sh   # Linux only
npm run pack:linux          # --linux dir; soft-ok if no vendor PG
npm run dist:linux:dir      # same via electron-builder
```

`extraResources` copies `vendor/pgsql` → `resources/pgsql` when present. At runtime
`PostgresManager` also honors `KKMAIL_PG_BIN`; a package built without PostgreSQL binaries
reports `stub: true` and the app refuses to start.

### macOS / Windows

- Use `npm run dist:mac` / `npm run dist:win` on the matching host or CI runner.
- Fetch or place PG binaries at **build time** into `desktop/vendor/pgsql/bin`
  (see `desktop/vendor/README.md`). The Linux fetch script does not auto-download
  for mac/win.
- Packaging (`pack:linux`) still succeeds when `vendor/pgsql` is absent, but that build cannot run.
