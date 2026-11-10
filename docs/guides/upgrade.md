# 升级

mail-core 部署的升级路径（Flask / SQLite / OutlookEmail v2 镜像路径已删除，勿再使用）。

仓库根目录可运行 `scripts/deploy_mail_core.sh` 串行执行部署：检查本地 `main` 与远端可快进、推送代码、创建并校验密封备份、标记旧镜像、重建 distributed Compose 服务、运行迁移，并检查 `/ready`、`/health`、worker 和 SPA 静态资源。脚本遇到分叉分支、未提交改动或门禁失败时停止，不执行 force-push。

1. **备份**：用密封备份包，不要对运行中的 PostgreSQL 数据目录做 `cp`。执行备份需保证 `pg_dump` 可用并在完整环境变量下运行。Docker 部署使用 `scripts/deploy_mail_core.sh`：备份以应用 UID 读取私有 `0600` blob，在容器私有目录生成密封包，再由宿主导出到 `0700` staging 并校验后发布；不要用 `--user` 覆盖成宿主 UID。源码路径执行前提：须在仓库根目录下运行，并设置 `PYTHONPATH=src`（源码布局下 `mail_core` 包位于 `src/`，缺此前提直接运行会报 `ImportError`）。下述命令为静态核对，未在本轮实测：
    ```bash
    PYTHONPATH=src python -c "from mail_core.backup import run_backup; print(run_backup(output_dir='/path/to/backups'))"
    ```
    未传 `output_dir` 时用 `MAIL_CORE_BACKUP_DIR`；会写包并校验。密钥（`--data-dir/secrets/` 或环境变量中声明的密钥）需单独安全脱机备份。
2. **升级数据库与更新代码 / 镜像**：
    - **存量库升级**：alembic `versions/` 仅保留统一基线单文件 `20261107_0001`，历史增量迁移已删除、无法重放，因此**不存在从任意历史版本自动升级到统一基线的通用路径**。旧迁移树的全部 31 个 revision 已在 `mail_core.db.baseline` 中显式枚举（`KNOWN_LEGACY_REVISIONS`，逐一自 Git 历史实证，不按日期形状猜测）：其中仅 `20261031_0030`、`20261107_0031` 两个 revision 的库可走窄转换（见下）；其余已知旧 revision（例如 `20261027_0029`，缺 `message_remote_image_allows`、`sender_remote_image_allows` 等后续迁移引入的表，离线工具无法补齐）归类为 LEGACY_UNSUPPORTED，启动与离线入口都会拒绝，并提示先用与该 revision 对应的历史版本 kkmail 升级、或从升级前的密封备份恢复到全新部署（全新库由 `alembic upgrade head` 建立统一基线）。未列入枚举的 revision 一律按 UNKNOWN_REVISION 拒绝；日期晚于当前 head 的 revision 归类为 NEWER_THAN_CODE（库由更新版本写入），须升级 kkmail 本身，切勿用旧备份覆盖。
    - **离线工具（受限，仅 PostgreSQL）**：`scripts/migrate_to_unified_baseline.py` 仅支持 PostgreSQL：`mail_core.db.baseline` 的只读校验（`SET TRANSACTION READ ONLY`）、窄转换（`pg_advisory_xact_lock` 加锁 + `jsonb` 巡检数据迁移）与 `folder_patrol_status` 建表均为 PostgreSQL 专用 SQL，非 PostgreSQL 连接串在只读校验、建表、数据迁移与窄转换各入口被显式拒绝（不静默跳过只读或加锁保护），不再兼容 SQLite。它与启动入口（`python -m mail_core` / `--migrate-only` / `--check-migrations`）共用 `mail_core.db.baseline.plan_migration` 的单一分类，两入口对同一数据库状态给出相同判定，不再各自判断；两入口还共用 `verify_for_plan` 按分类执行校验，启动的 check 与正常启动对已在统一基线的库同样执行完整校验（`verify_baseline_schema`），漂移库在部署 preflight 即被拒绝，与离线工具结论一致。**无 `alembic_version` 且存在任何统一基线业务表（`REQUIRED_TABLES`）的库，两个入口一律拒绝**（即使 32 张表齐全也不盖印），须从已知良好备份恢复并显式迁移数据；空库由启动执行 `alembic upgrade head` 建表，离线工具只提示走启动/Alembic、不建表不盖印。离线工具仅适用于已处于 `20261031_0030` 或 `20261107_0031`、仅缺 `folder_patrol_status` 表的极窄已知 legacy 情形：补建该表、迁移 `sync_checkpoints.cursor` 里的巡检数据，校验通过后把 `alembic_version` 校准至 `20261107_0001`。离线工具实际校验范围：已在统一基线的库、以及窄转换完成之后（同一写事务内、校准 `alembic_version` 之前），都走 `verify_baseline_schema`——以 ORM metadata 为唯一真相，用 Alembic `compare_metadata` 对全部 32 张表做完整比对（列名、PostgreSQL 精确类型、可空性、主键/外键/唯一约束、索引），任何差异即拒绝；已知 legacy 在转换前另走 `verify_narrow_legacy_schema`，仅查转换前置条件（其余基线表存在性、`sync_checkpoints` 的主键/外键与 JSON cursor 及数据可读性、`folder_patrol_status` 既存时的列定义）。对未列入枚举的未知 revision、`alembic_version` 多行、不受窄转换支持的已知旧版本或校验不通过的库会明确拒绝：未知 revision 提示从备份恢复，已知旧版本提示先用对应历史版本升级。该工具**未随 Docker 镜像或桌面 sidecar 分发**，须在源码布局下运行。脚本不提供默认连接串，必须显式设置 `MAIL_CORE_DATABASE_URL` 或传 `--database-url`，否则直接以退出码 2 结束：
        ```bash
        export MAIL_CORE_DATABASE_URL='postgresql+psycopg://kkmail:<POSTGRES_PASSWORD>@127.0.0.1:5433/kkmail_mail'
        PYTHONPATH=src python scripts/migrate_to_unified_baseline.py --dry-run
        PYTHONPATH=src python scripts/migrate_to_unified_baseline.py
        ```
        Docker Compose 把 PostgreSQL 映射到宿主 `127.0.0.1:5433`（容器内为 `5432`）；从宿主运行脚本须用宿主端口 `5433` 与 `127.0.0.1`，不可沿用容器内服务名 `postgres`。非 Docker 部署按实际连接串填写。`--dry-run` 只校验、不写 `alembic_version`。
    - **常规部署更新**：
        - Docker Compose 部署：执行 `docker compose -f docker-compose.mail-core.yml up --build -d api worker`，依赖会自动拉起 `migrate` 容器执行数据库迁移，成功后启动新版 `api` 与 `worker`。
        - 非 Docker 部署：拉取代码、更新依赖 `pip install -r requirements-mail-core.txt`、构建前端 SPA 并执行 `alembic -c src/mail_core/db/alembic.ini upgrade head`，然后重启进程。
    - **数据搬迁的写入暂停与回滚恢复点**：迁移容器运行前部署先停止 api 与 worker，隔离旧写入；回滚恢复点是迁移前创建并校验的密封备份快照，快照之后产生的新写入不在恢复点内（恢复即回到快照时刻）。
3. **确认**：`/ready` 返回 200（schema 与代码 head 一致）。

## 回滚

- **降级风险**：统一基线迁移 `20261107_0001` 绝不可随意降级（其 `downgrade()` 会破坏性 DROP 全部 32 张业务表，含 `message_search`、`messages`、`accounts` 等核心表）。旧编号 `20261020_0001` / `20261020_0002` 已随历史迁移脚本删除，不再是真实风险对象。涉及核心表结构变动的降级必须通过导入升级前备份包恢复，不可依赖单向 downgrade。
- **私有权限归一化**：blob 文件应为应用 UID + `0600`、私有目录 `0700`，恢复后不得继承归档 UID 或 umask。存量 mode 漂移时在应用 UID 容器内显式执行 `python -m mail_core.blobs.permissions /var/lib/kkmail/blobs`；需要修复 owner 时以 root + `CHOWN/FOWNER/DAC_OVERRIDE` 加 `--target-uid 10001 --target-gid 999` 执行受控 chown（异属主 0700 目录需 DAC_OVERRIDE 才能遍历）。宿主备份目录可用 `.venv/bin/python scripts/normalize_mail_core_permissions.py <dir>`。不要在应用启动时做递归权限修补。
- **密钥退休**：轮换期间必须保留 `MAIL_CORE_BLOB_KEYS` 中全部旧密钥。`run_rewrap()` 先重加密所有 blob 文件并逐文件提交版本元数据，确认无错误且没有旧版本 blob 后才重加密 `credential_secrets`。只有结果同时满足 `errors == []`、`remaining_old_version_blobs == 0`、`remaining_old_version_credentials == 0` 和 `safe_to_retire_old_keys == true`，才可从 keyring 移除旧密钥。若 `limit` 后仍有旧版本文件、未配置数据库、凭据迁移未提交、校验失败或任一旧版本仍有引用，必须保留旧密钥，完成剩余迁移后重新检查结果。
