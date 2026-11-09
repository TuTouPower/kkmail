# 升级

mail-core 部署的升级路径（Flask / SQLite / OutlookEmail v2 镜像路径已删除，勿再使用）。

仓库根目录可运行 `scripts/deploy_mail_core.sh` 串行执行部署：检查本地 `main` 与远端可快进、推送代码、创建并校验密封备份、标记旧镜像、重建 distributed Compose 服务、运行迁移，并检查 `/ready`、`/health`、worker 和 SPA 静态资源。脚本遇到分叉分支、未提交改动或门禁失败时停止，不执行 force-push。

1. **备份**：用密封备份包，不要对运行中的 PostgreSQL 数据目录做 `cp`。执行备份需保证 `pg_dump` 可用并在完整环境变量下运行。Docker 部署使用 `scripts/deploy_mail_core.sh`：备份以应用 UID 读取私有 `0600` blob，在容器私有目录生成密封包，再由宿主导出到 `0700` staging 并校验后发布；不要用 `--user` 覆盖成宿主 UID。源码路径执行前提：须在仓库根目录下运行，并设置 `PYTHONPATH=src`（源码布局下 `mail_core` 包位于 `src/`，缺此前提直接运行会报 `ImportError`）。下述命令为静态核对，未在本轮实测：
    ```bash
    PYTHONPATH=src python -c "from mail_core.backup import run_backup; print(run_backup(output_dir='/path/to/backups'))"
    ```
    未传 `output_dir` 时用 `MAIL_CORE_BACKUP_DIR`；会写包并校验。密钥（`--data-dir/secrets/` 或环境变量中声明的密钥）需单独安全脱机备份。
2. **升级数据库与更新代码 / 镜像**：
    - **存量库升级**：alembic `versions/` 仅保留统一基线单文件 `20261107_0001`，历史增量迁移已删除、无法重放，因此**不存在从任意历史版本自动升级到统一基线的通用路径**。早于 `20261031_0030` 的旧库（例如 `20261027_0029`）缺少 `message_remote_image_allows`、`sender_remote_image_allows` 等后续迁移引入的表，离线工具无法补齐，启动会被拒绝。可靠做法是从升级前的密封备份恢复到全新部署（全新库由 `alembic upgrade head` 建立统一基线）。
    - **离线工具（受限）**：`scripts/migrate_to_unified_baseline.py` 仅适用于已处于 `20261031_0030` 或 `20261107_0031`、仅缺 `folder_patrol_status` 表的极窄情形：补建该表、迁移 `sync_checkpoints.cursor` 里的巡检数据，校验表名与关键列名（**不校验列类型、可空性、默认值、索引与外键，非全量 schema**），通过后才把 `alembic_version` 校准至 `20261107_0001`；对更早版本或校验不通过的库会明确拒绝并提示从备份恢复。该工具**未随 Docker 镜像或桌面 sidecar 分发**，须在源码布局下运行：
        ```bash
        PYTHONPATH=src python scripts/migrate_to_unified_baseline.py --dry-run
        PYTHONPATH=src python scripts/migrate_to_unified_baseline.py
        ```
        `--dry-run` 只校验、不写 `alembic_version`。
    - **常规部署更新**：
        - Docker Compose 部署：执行 `docker compose -f docker-compose.mail-core.yml up --build -d api worker`，依赖会自动拉起 `migrate` 容器执行数据库迁移，成功后启动新版 `api` 与 `worker`。
        - 非 Docker 部署：拉取代码、更新依赖 `pip install -r requirements-mail-core.txt`、构建前端 SPA 并执行 `alembic -c src/mail_core/db/alembic.ini upgrade head`，然后重启进程。
3. **确认**：`/ready` 返回 200（schema 与代码 head 一致）。

## 回滚

- **降级风险**：统一基线迁移 `20261107_0001` 绝不可随意降级（其 `downgrade()` 会破坏性 DROP 全部 31 张业务表，含 `messages`、`accounts` 等核心表）。旧编号 `20261020_0001` / `20261020_0002` 已随历史迁移脚本删除，不再是真实风险对象。涉及核心表结构变动的降级必须通过导入升级前备份包恢复，不可依赖单向 downgrade。
- **私有权限归一化**：blob 文件应为应用 UID + `0600`、私有目录 `0700`，恢复后不得继承归档 UID 或 umask。存量 mode 漂移时在应用 UID 容器内显式执行 `python -m mail_core.blobs.permissions /var/lib/kkmail/blobs`；需要修复 owner 时以 root + `CHOWN/FOWNER/DAC_OVERRIDE` 加 `--target-uid 10001 --target-gid 999` 执行受控 chown（异属主 0700 目录需 DAC_OVERRIDE 才能遍历）。宿主备份目录可用 `.venv/bin/python scripts/normalize_mail_core_permissions.py <dir>`。不要在应用启动时做递归权限修补。
- **密钥退休**：轮换期间必须保留 `MAIL_CORE_BLOB_KEYS` 中全部旧密钥。`run_rewrap()` 先重加密所有 blob 文件并逐文件提交版本元数据，确认无错误且没有旧版本 blob 后才重加密 `credential_secrets`。只有结果同时满足 `errors == []`、`remaining_old_version_blobs == 0`、`remaining_old_version_credentials == 0` 和 `safe_to_retire_old_keys == true`，才可从 keyring 移除旧密钥。若 `limit` 后仍有旧版本文件、未配置数据库、凭据迁移未提交、校验失败或任一旧版本仍有引用，必须保留旧密钥，完成剩余迁移后重新检查结果。
