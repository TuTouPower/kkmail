# 桌面端 (Desktop)

用于承载 React 前端界面与 mail-core 后端服务的 Electron 桌面外壳。

## 开发与安装

```bash
cd src/desktop
npm ci          # 推荐使用 ci (lockfile) 而非 npm install
npm start
```

推荐使用 Node ≥ 22.12（Electron 44 引擎范围）。详细指南见 `../../docs/guides/desktop.md`。

### 环境变量

|环境变量|消费模块|用途说明|
|---|---|---|
|`KKMAIL_PG_BIN`|Electron / PostgresManager|覆盖 `initdb`/`pg_ctl` 所在二进制目录路径|
|`KKMAIL_PG_PORT`|PostgresManager|本地回环 PostgreSQL 端口（整数 1–65535）|
|`KKMAIL_PG_PASSWORD`|PostgresManager|覆盖每次安装生成的专用 PG 密码（通常生成并保存在 `secrets/`）|
|`KKMAIL_DESKTOP_PORT`|Electron 主进程|mail-core API/UI 本地回环端口（整数 1–65535，默认 18765）|
|`PYTHON`|Electron 主进程 (仅开发)|开发环境下用于拉起 `mail_core` 的 Python 可执行文件路径（Windows 默认 `python`，其余系统默认 `python3`）|
|`KKMAIL_FRONTEND_DIST`|mail-core API|可选的 SPA 生产构建产物目录路径（`src/frontend/dist`）|
|`MAIL_CORE_*`|mail-core 子进程|由 `startup.js` 显式注入（DB URL、blob 密钥、数据目录等）——不从父 shell 环境继承|
|`PGPORT`, `PGPASSWORD`|`pg_ctl` / `createdb`|仅作为单次调用的显式附加参数传入（`PGPORT` 传入 `pg_ctl start`，`PGPASSWORD` 传入 `createdb`）；`scrubEnv` 绝不继承父级 `PG*` 变量|

打包说明：macOS DMG/ZIP 产物固定命名为 **`kkmail.dmg`** / **`kkmail.zip`** (`build.mac.artifactName`)。

## 启动时序 (`main.js`)

1. `PostgresManager` 在 `userData/mail-core-data/` 下启动仅限本地回环的独立 PostgreSQL 集群（独立于安装目录；每次安装生成随机口令，使用 `scram-sha-256` 认证）。缺少 PG 二进制文件属于致命错误——见 `../../docs/guides/desktop.md`。
2. 拉起携带 `--data-dir <userData>/mail-core-data` 的 mail-core：开发环境直接从仓库以 `python3 -m mail_core` 运行；生产打包环境调度 PyInstaller 产物 `resources/backend/kkmail-backend`（从根目录通过 `scripts/build-sidecar.sh` 构建）。打包应用缺少 sidecar 产物时拒绝启动。
3. mail-core 在 `mail-core-data/secrets/`（权限 0600）中生成当前安装的会话密钥、Blob 密钥与备份密钥，执行数据库迁移，并在 `127.0.0.1` 启动 API 服务与内嵌 Worker。
4. `/health` 探测通过后打开应用窗口。首次运行会弹出一次性初始登录密码，用户在设置中完成改密后自动销毁。

外链仅对 `https:` 与 `mailto:` 在系统默认浏览器中打开。本地回环 `http:` 绝不向外部打开（防止探测本地端口）——仅同源应用页面保留在窗口内，所有离开本地源的导航一律拦截。本地端口绝不暴露至 `127.0.0.1` 之外。

## 会话加固 (`hardening.js`)

- `will-attach-webview` 永远阻止（`webviewTag: false`）；
- 系统权限请求与检查默认全量拒绝，仅保留唯一例外：来自应用自身主框架（`isMainFrame: true` 且同源）的 `clipboard-sanitized-write`；
- 每个响应强制注入严格的 Content-Security-Policy（`default-src 'self'`，无 `object`/`frame-ancestors`，仅连接自身）。

## 测试套件 (`npm test`)

|测试文件|覆盖范围|
|---|---|
|`paths.test.js`|Sidecar 路径与 `extraResources` 过滤器匹配 `kkmail-backend`；外部 URL、弹窗与导航防护|
|`hardening.test.js`|CSP、webview 与权限边界断言|
|`postgresManager.test.js`|数据根目录、pwfile 0600 权限、端口校验、stop 幂等性、二进制缓存|
|`startup.test.js`|`scrubEnv` 白名单、日志脱敏、进程树清理、后端退出处理|
|`logRotation.test.js`|日志轮转流：按体积轮转、历史保留、异步写盘|
|`desktopLog.test.js`|桌面日志器：脱敏、日志级别、轮转集成|
|`clipboard.test.js`|剪贴板净化写（需要 Electron 运行环境）|
|`windowOptions.test.js`|各平台主窗口参数|
|`packLinux.test.js`|Linux 打包脚本 (`pack-linux.js`) 行为校验|
|`scripts/packaged_smoke_db.test.js`|打包冒烟：通过 `psql` 验证标记写入与数据持久化|
|`scripts/packaged_smoke.test.js`|打包冒烟：端口常量规范与失败清理辅助逻辑|
|`oauth_integration.test.js`|Electron Microsoft OAuth 授权全链路（需配置 `KKMAIL_OAUTH_TEST_*`）|

## 子进程安全边界 (`startup.js` / `postgresManager.js`)

- mail-core 仅注入 `scrubEnv` 净化环境加显式 `MAIL_CORE_*` 配置；PostgreSQL 工具使用 `scrubEnv`；
    `PGPORT` 仅追加至 `pg_ctl start`，`PGPASSWORD` 仅追加至 `createdb`；父进程变量绝不隐式继承；
- 后端 **标准 I/O 管道重定向** 至 `mail-core-data/mail-core.log` 并强制脱敏密码与数据库 URL（不使用 `inherit`）；
- 停机采用 **单飞行次管理 (single-flight)**：向 Unix 进程组或子进程发送 SIGTERM，4 秒未退出升级为 SIGKILL / `taskkill /T /F`；`PostgresManager.stop()` 保持幂等；
- PG 二进制探测结果带有带超时保护的本地**缓存**；在写入 `postgresql.conf` 前强制校验 `KKMAIL_PG_PORT` 为 1–65535 整数；
- initdb `--pwfile` 保存在 `secrets/` 目录且模式为 `0600`，在 `finally` 块中自动 unlink 销毁（启动时自动清理历史残留 `.pgpass-init`）；
- 数据根目录优先使用 Electron `userData`，次选 `~/.kkmail`，再次选 `XDG_DATA_HOME` / 按 UID 隔离临时目录——严禁使用共享的 `/tmp/.kkmail`。
