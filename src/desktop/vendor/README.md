# 桌面端 PostgreSQL 二进制依赖 (Vendor Binaries)

将官方 PostgreSQL **16** 二进制执行文件放置在 `pgsql/bin/` 目录下：

```
desktop/vendor/pgsql/bin/initdb
desktop/vendor/pgsql/bin/pg_ctl
desktop/vendor/pgsql/bin/postgres
```

**严禁将二进制文件提交至 Git 仓库**（见 `.gitignore`）。

## Linux (开发 / CI 环境)

```bash
./scripts/fetch-pg-binaries.sh
# 使用 theseus-rs 便携打包版；可通过 PG_VENDOR_URL=... 覆盖下载源
```

默认的 PostgreSQL 16.6.0 目标归档使用脚本内锁定的 SHA-256 校验和。未锁定的镜像源或版本默认拒绝下载；仅在显式传入 `--allow-unpinned` 时才允许同源校验和回退，推荐显式传入 `PG_VENDOR_SHA256` 锁定自定义归档。

桌面端打包版本（16.6.0）与服务端/测试镜像（postgres:16.15）版本故意保持独立（**intentionally independent**）：桌面二进制文件来源于 theseus-rs 预编译的便携压缩包，而服务端运行官方 Docker 镜像。两者均保持在 PostgreSQL 16 主版本线上；小版本差异属于预期行为，桌面端版本的升级是经过审慎锁定刷新的人工决策，而非自动跟进服务端补丁（详见 `scripts/fetch-pg-binaries.sh` 脚本说明）。

`PostgresManager` 解析优先级：`KKMAIL_PG_BIN` 环境变量 → `desktop/vendor/pgsql/bin` 本地目录 → 系统 `PATH`。

## macOS / Windows (构建期下载)

获取脚本对 `--os macos|windows` 会输出指导说明并以状态码 0 退出。
在这些平台上进行打包或 CI 时，应在**构建时**下载匹配的官方或 EnterpriseDB / Postgres.app 二进制包并解压至对应目录。
