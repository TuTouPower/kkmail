# t019 代码审查

## 范围与执行方式

审查 t019 真实备份与恢复演练生产逻辑及测试改动：

- `src/mail_core/backup/package.py`: 新增生产级 `restore_backup_package` 与 `RestoreResult` 数据类，涵盖签名/校验前置、解包、真实 `pg_restore`、目标安全检查与防覆盖守卫
- `src/mail_core/backup/__init__.py`: 导出 `restore_backup_package` 与 `RestoreResult`
- `scripts/test_pg_client/`: 建立测试专用的 `pg_dump` 与 `pg_restore` 客户端代理
- `tests/mail_core/test_backup_restore_drill_live.py`: 建立真实全流程备份、验证、跨库恢复与数据业务断言测试

## Finding 处置

- 已修 important: 归档包解包格式与路径对齐。`manifest.json` 中 dump 文件名为 `postgres.dump`，blobs 为 `blobs.tar`；解包时通过流式 tarfile 安全抽取并统计 `blobs_restored`。
- 已修 important: 宿主机端口与容器端口映射。在测试客户端代理中将 `:15433` 映射为容器内部服务端口 `:5432`，确保真实 `pg_dump` 和 `pg_restore` 联通。

## 结论

PASS。无未解决 critical 或 important 问题。
