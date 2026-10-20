# 升级

mail-core 部署的升级路径（Flask / SQLite / OutlookEmail v2 镜像路径已删除，勿再使用）。

1. **备份**：用密封备份包，不要对运行中的 PostgreSQL 数据目录做 `cp`。执行备份需保证 `pg_dump` 可用并在完整环境变量下运行：
   ```bash
   python -c "from mail_core.backup import run_backup; print(run_backup(output_dir='/path/to/backups'))"
   ```
   未传 `output_dir` 时用 `MAIL_CORE_BACKUP_DIR`；会写包并校验。密钥（`--data-dir/secrets/` 或环境变量中声明的密钥）需单独安全脱机备份。
2. **更新代码 / 镜像**：
   - Docker Compose 部署：执行 `docker compose -f docker-compose.mail-core.yml up -d --build`，依赖会自动拉起 `migrate` 容器执行数据库迁移，成功后启动新版 `api` 与 `worker`。
   - 非 Docker 部署：拉取代码、更新依赖 `pip install -r requirements-mail-core.txt`、构建前端 SPA 并执行 `alembic -c mail_core/db/alembic.ini upgrade head`，然后重启进程。
3. **确认**：`/ready` 返回 200（schema 与代码 head 一致）。

## 回滚

- **降级风险**：基线迁移 `20261020_0001` 与核心统一模式 `20261020_0002` 绝不可随意降级（执行 downgrade 会破坏性 DROP `messages`、`accounts` 等核心业务表）。涉及核心表结构变动的降级，必须通过导入升级前备份包进行恢复，不可依赖单向 downgrade。
- **密钥退休**：轮换密钥后必须保留旧密钥版本条目（`MAIL_CORE_BLOB_KEYS`）。在退休旧密钥前，不仅要执行 `mail_core.blobs.rotate.run_rewrap()` 完成所有存储 blob 的重新加密，还必须确保凭据表（`credential_secrets`，其加密密钥派生自 blob key）中的记录已完成重加密迁移，否则旧密钥移除后会导致已有账户凭据无法解密。
