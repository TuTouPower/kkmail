---
pid: "p091"
slug: "idle_watcher_catchup_backoff_semantics"
status: "closed"
resolution: "resolved"
reason: "_fingerprint 移除可变 updated_at，改用稳定凭据身份；4 条 idle watcher 契约用例与完整 PG 套件 2243 passed 全绿"
fix_ref: "main"
---
# p091 t073 两条 idle watcher 用例失败：补偿失败退避与断开恢复

- 现象：完整 PostgreSQL 套件稳定失败 2 条：
    - `test_t061_idle_watcher.py::test_t073_ac002_persistent_catchup_failure_releases_seat_for_polling`：持续补偿入队失败未进入 `backoff`，日志反复出现 `retrying in 0.20s (1/3)`。
    - `test_t061_idle_watcher.py::test_t073_ac003_stop_during_catchup_retry_returns_promptly`：停止单个 watch 后仍持续产生补偿调用，计数不收敛。
- 影响：t073 承诺的"补偿失败退避并让位 t057 轮询"语义未被当前实现满足。t088 曾尝试把 `idling` 状态推迟到补偿成功、并在重试中固定 `backoff`，修好了这两条，但导致 `test_blocked_watch_deregisters_and_retries_after_expiry` 与 `test_ac003_manager_recovers_after_disconnect` 回归，已全部撤回；说明状态机改动需整体设计而非局部调整。
- 根因：`_fingerprint` 把 `account.updated_at` 当作凭据指纹。连接成功后 `record_connectivity_success` 更新 `updated_at`，reconcile 因此判定凭据轮换并关闭/重开 watch；被关闭 watch 的 stop_event 使 `_enqueue_catchup` 每轮在第一次失败就退出，表现为重试计数不收敛与退避状态不稳定。凭据指纹只应由稳定身份字段构成。
- 测试缺口：现有 4 条 t073/t061 用例即契约测试，修复后需同时满足全部 4 条。
- 线索：`.scratch/t088_full_pg.log`（调整前 4 条失败）、`.scratch/t088_full_pg_final.log`（状态调整后剩余 2 条失败及新回归 2 条）。
- 处理：main；resolution=resolved；reason=\_fingerprint 移除可变 updated_at，改用稳定凭据身份；4 条 idle watcher 契约用例与完整 PG 套件 2243 passed 全绿
