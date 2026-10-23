# p036 同步任务失败时内部重排队与 Worker 重试叠加

- 现象：`sync_folder_delta` 遇到 provider 错误时，函数先自行创建一条延迟重试任务，再返回 `provider_error`；Worker 的 `_evaluate_result` 随后又对原任务执行 `fail_job`。隔离 PostgreSQL 最小复现确认一次失败会留下两条同账号、同文件夹的 `pending` 任务，一条来自 provider 函数、一条来自 Worker 重试。`sync_folder_metadata` 的 `lease_busy` / `cursor_invalid` 和 `sync_folder_delta` 的 `lease_busy` / `cursor_invalid` 存在同类双排队路径。
- 影响：每次 provider 故障都会增加重复任务与登录请求，延长错误风暴并触发邮箱服务商限流。当前本地实例观察到一个 126 IMAP 账号连续收到 `Too many login attempts, try again later`，近两小时 Worker 产生 365 条错误/失败日志；数据库中该账号多个文件夹累计有大量失败 delta 任务。
- 根因：`src/mail_core/sync/delta.py` 在 `lease_busy`（约第 274–285 行）与 provider error（约第 366–389 行）中创建后继任务后仍返回非成功状态；`src/mail_core/sync/engine.py` 的 metadata `lease_busy`（约第 248–261 行）和 cursor invalid（约第 326–349 行）也先入队再返回。`src/mail_core/worker/handlers.py` 的 `_evaluate_result` 仅把 `ok`、`sync_disabled`、`skipped`、`rate_limited` 当作成功，其余状态都对当前任务调用 `fail_job`，造成两个重试源叠加。已扫 `sync_account_folders` 与 `reconcile_folder`，未发现相同的“内部入队后返回非成功”路径；`rate_limited` 由 Worker 作为成功完成，因此不会重复重试。
- 测试缺口：现有 `test_a27_sync_folder_delta_sanitizes_errors` 只验证错误脱敏与 payload，未断言后继任务数量；`test_a28_worker_handler_rate_limited_single_job` 仅覆盖 `rate_limited` 这一正常单后继路径。需补 PostgreSQL 集成测试，覆盖 delta `provider_error` / `lease_busy` 及 metadata `lease_busy` / `cursor_invalid`，断言原任务与内部后继合计恰为一条待处理任务。
- 线索：`.scratch/repro_sync_retry_double_enqueue.py`
- 处理：t049
