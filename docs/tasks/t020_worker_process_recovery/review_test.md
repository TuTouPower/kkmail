# t020 测试审查

## 范围与执行方式

核查 t020 多进程并发、故障恢复与进程组安全清理测试套件：

- `tests/mail_core/test_worker_process_recovery.py` (3 项真实进程级测试)
- `tests/mail_core/test_sync_leases_jobs.py` (单测级双连接租约测试)
- `tests/mail_core/test_chaos_lease_recovery.py` (单测级回退时间租约测试)

## 门禁验证结果

1. **多进程并发与恢复套件**: `scripts/run-mail-core-tests.sh run -k test_worker_process_recovery` 3 passed (8.25s)。
2. **租约与锁核心套件**: `scripts/run-mail-core-tests.sh run -k "test_sync_leases_jobs or test_chaos_lease_recovery"` 6 passed。
3. **进程组清理**: 验证 `managed_subprocesses` fixture 使用 `start_new_session=True` 与 `os.killpg(..., signal.SIGKILL)`，测试结束后无僵尸进程滞留。

## 结论

PASS。测试脱离了单纯在 DB 里改时间戳模拟崩溃的局限，触达了真实操作系统进程终止、自动超时回收和跨进程通知通信。
