# Task review t057（reviewer_focus: 代码）

## Round 1 (2026-10-27T19:38:00+08:00)

- reviewed_at: 2026-10-27T19:38:00+08:00
- reviewed_scope: 6c4351a0be90c36e

代码复审 PASS。
实现严格遵照 spec 契约区与架构设计：
1. `src/mail_core/worker/main.py`：新增 `schedule_periodic_inbox_sync` 与 `_schedule_periodic_sync_once`，实现 1200 秒（20 分钟）收件箱巡检调度；计算 `stagger_step` 错峰平摊各账号的 `run_after`；严格过滤 `sync_enabled=False` 账号及 `paused` 收件箱；在 `run()` 主循环中每 60 秒触发一次巡检并独立隔离异常。
2. `src/mail_core/sync/delta.py`：彻底移除第 650–670 行的尾递归 30 秒自调度逻辑；在 `totals.get("upserted", 0) > 0` 时自动入队 `ARCHIVE_MIME_BATCH`（优先级 60，dedupe key 为 `archive_mime_batch:{account_id}`）。
3. `src/mail_core/sync/execution.py`：在 `_successor_is_periodic` 中支持当 `result.get("exhausted")` 时判定为独立后继，避免已完成请求误绑定后继。
4. 配置与文档：`config/.env.example`、`src/mail_core/README.md`、`docs/blueprint/architecture.md` 与 `docs/specs/mail_sync_and_storage.md` 契约文档均同步更新。

零 finding。

verdict: PASS
