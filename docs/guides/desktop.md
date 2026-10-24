# mail-core 桌面 PostgreSQL 子进程

架构依据：`docs/blueprint/architecture.md`「系统拓扑与进程划分」中的「桌面集成」。

## 数据目录（安装目录之外）

Electron 使用 `app.getPath('userData')/mail-core-data/`：

|子路径|用途|
|---|---|
|`pgdata/`|PostgreSQL 数据目录|
|`blobs/`|内容寻址 MIME blob|
|`backups/`|备份包输出|
|`README-DO-NOT-DELETE.txt`|提醒卸载默认不得删除|

**卸载默认不得删除**该目录；清除需用户显式「清除本地邮件数据」。

## API（`src/desktop/postgresManager.js`）

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
2. `src/desktop/vendor/pgsql/bin`（官方二进制；**不进 git**）
3. 系统 `PATH` 上的 `initdb` / `pg_ctl`

获取开发用二进制：

```bash
# Linux
./scripts/fetch-pg-binaries.sh
# macOS/Windows: download-at-build（见 src/desktop/vendor/README.md）
# 或手动解压到 src/desktop/vendor/pgsql/bin/
```

详见 [`src/desktop/vendor/README.md`](../../src/desktop/vendor/README.md)。

无二进制时：`start()` 创建数据目录并返回 `{ stub: true }`，`main.js` 将其视为致命错误并提示（mail-core 是唯一后端，没有无 PG 的回退）。

## 启动顺序

1. `PostgresManager.start()`：loopback 集群，`scram-sha-256`，每次安装随机密码（`secrets/pg-password`，0600），首次 `createdb kkmail_mail`。
2. 启动 `python -m mail_core --data-dir <dataRoot>`（打包后为 sidecar `kkmail-backend`）：生成/加载 `secrets/` 下 session/blob/backup 密钥，`alembic upgrade head`，API + 内嵌 worker 绑定 `127.0.0.1`。
3. `/health` 就绪后打开窗口；首次运行显示一次随机初始登录密码，修改密码后 `initial-password.txt` 被删除。

## 与 Docker 的关系

桌面与 Docker **同一 PG 主版本目标、同一 Alembic schema**。开发可用 `docker-compose.mail-core.yml` / `docker run postgres:16`；桌面路径用本地子进程。

## 打包构建 (electron-builder)

桌面壳层面向 **Electron 44**（Chromium 152 / Node 24）。推荐使用 Node ≥ 22.12 在 `src/desktop/` 目录下执行构建：

```bash
cd src/desktop
npm ci
# 拉取跨平台 PostgreSQL 便携依赖：
../../scripts/fetch-pg-binaries.sh
npm run pack:linux          # 构建 Linux 目录包
npm run dist:linux:dir      # 通过 electron-builder 打包
```

`extraResources` 在存在时将 `vendor/pgsql` 复制至 `resources/pgsql`。运行时 `PostgresManager` 亦支持通过环境变量 `KKMAIL_PG_BIN` 指定二进制路径；若未提供 PostgreSQL 依赖，应用将被标记为 `stub: true` 并在启动时明确报错拒绝运行。

### `pack:linux` 本地构建策略

`npm run pack:linux`（`src/desktop/scripts/pack-linux.js`）默认将 `electron-builder` 缺失、下载失败或打包失败作为构建失败处理并返回非零退出码。

- 本地脚手架需要在缺少 `electron-builder` 或网络异常时软退出，可直接运行 `KKMAIL_PACK_SOFT=1 node scripts/pack-linux.js`；该开关不由任何 npm 打包脚本设置，且通过 npm 打包脚本调用时会被忽略；
- 缺少 `vendor/pgsql` 时可生成无内置 PostgreSQL 的构建壳，但运行须有可用本地 PostgreSQL 二进制（内置或环境变量 `KKMAIL_PG_BIN` / 系统 `PATH`），缺失可用本地二进制即启动失败报错；应用仅管理本地 PostgreSQL 进程，不支持外接远程数据库，请区分二进制来源与外部数据库连接。

### macOS 与 Windows 构建说明

- 在对应操作系统上运行 `npm run dist:mac` 或 `npm run dist:win`。
- 构建前可通过根目录 `scripts/fetch-pg-binaries.sh` 脚本自动下载匹配目标平台的 PostgreSQL 便携版本，脚本会自动处理 macOS 下的 `@rpath` 动态链接库修正。

## 会话安全（Electron）

`src/desktop/main.js` 在 `app.whenReady` 时调用 `applySessionHardening()`（逻辑在 `src/desktop/hardening.js`）：

1. `will-attach-webview` → `preventDefault`（且 `webviewTag: false`）
2. 权限请求 / 检查仅允许可信 `appOrigin` 的顶层页面（`details.isMainFrame === true`）写入 `clipboard-sanitized-write`；邮件 iframe、外部页面、子 frame 及其它权限（包括 `clipboard-read`）全部拒绝
3. `session.webRequest.onHeadersReceived` 注入限制性 CSP

详见 `docs/guides/security.md`「桌面 Electron」。
