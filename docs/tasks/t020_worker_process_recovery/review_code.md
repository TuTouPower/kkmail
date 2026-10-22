# t020 代码审查

## 范围与执行方式

审查 t020 多进程 Worker 并发竞争与故障恢复测试实现：

- `src/mail_core/worker/main.py`: 支持通过环境变量 `MAIL_CORE_RECLAIM_STALE_SECONDS` 配置陈旧任务 reclaim 判定阈值，默认保持 300 秒，支持测试短周期自然超时演进
- `tests/mail_core/test_worker_process_recovery.py`: 建立多进程并发认领（SKIP LOCKED）、SIGKILL 强杀后自然过期 reclaim、租约 fencing token 阻断旧提交、独立进程跨进程 LISTEN/NOTIFY 与事务回滚隔离验证

## Finding 处置

- 已修 important: 独立 Worker 进程环境变量注入。为子进程显式注入 `PYTHONPATH=src`、`MAIL_CORE_BLOB_KEY_V1`、`MAIL_CORE_SECRET_KEY`，确保在任何执行环境下子进程 Worker 均能正常初始化。
- 已修 important: 任务状态枚举对齐。`JobStatus.DONE`（而非已废弃的 COMPLETED），`assert_fencing` 关键字传参对齐。

## 结论

PASS。无未解决 critical 或 important 问题。
