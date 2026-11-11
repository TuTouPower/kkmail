# 004 Worker 并发执行器执行位取 total_slots 与单副本约束 (t063)（2026-10-30）

- **决策**：
    1. Worker 并发执行位数量严格等于集中配置的 `total_slots`（默认 8），不另增 `worker_concurrency` 之类独立配置项。
    2. 废除原串行执行器下的 `worker_claim_batch` / `MAIL_CORE_CLAIM_BATCH`。
    3. 当前架构明确约束部署为**单 Worker 进程**。若未来扩展为多 Worker 副本部署，必须改为「在认领前先原子获取 provider 连接槽 permit，成功后才执行 claim_jobs」，避免多进程并发争抢连接预算。
- **背景与原因**：
    1. 系统已有 `connection_slots` 统一管理供应商并发连接预算（总预算 `total_slots`，前台保留 `background_start_slot`），执行位与连接预算 1:1 对齐最简洁无冗余。
    2. 单 Worker 进程内直接通过在途计数调度准入已可完全保证 8/6 容量约束与同账号租约任务互斥，避免了跨进程分布式锁的高额开销。
