# 升级

1. **备份**：`python -c "from mail_core.backup import run_backup; print(run_backup(output_dir='/path/to/backups'))"`（未传 `output_dir` 时用 `MAIL_CORE_BACKUP_DIR`；会写包并校验），并单独保存密钥（`--data-dir/secrets/` 或你的密钥管理）。可用 `scripts/mail-core-backup-restore-drill.sh` 演练恢复。
2. **更新代码 / 镜像**：`git pull` 或 `docker compose -f docker-compose.mail-core.yml build`。
3. **迁移**：compose 的 `migrate` 服务、`python -m mail_core`（默认）或手动 `alembic -c mail_core/db/alembic.ini upgrade head`。
4. **确认**：`/ready` 返回 200（schema 与代码 head 一致）。

## 回滚

- 代码回到旧版本前执行 `alembic -c mail_core/db/alembic.ini downgrade <旧 revision>`；基线迁移（`20261020_0001`）不可降级，无法降级的数据变更以备份包恢复。
- 密钥轮换后保留旧版本密钥（`MAIL_CORE_BLOB_KEYS` 里的旧条目），直到 `mail_core.blobs.rotate.run_rewrap()` 完成重新加密。
