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
./scripts/fetch-pg-binaries.sh
# 或手动解压到 desktop/vendor/pgsql/bin/
export KKMAIL_MAIL_CORE_PG=1   # Electron main 在启动 Flask 后尝试 start()
```

详见 [`desktop/vendor/README.md`](../desktop/vendor/README.md)。

无二进制时：`start()` 仍会创建数据目录并返回 `{ stub: true }`，Flask 默认路径不受影响。

## 与 Docker 的关系

桌面与 Docker **同一 PG 主版本目标、同一 Alembic schema**。开发可用 `docker-compose.mail-core.yml` / `docker run postgres:16`；桌面路径用本地子进程。
