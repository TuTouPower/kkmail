# p063 邮件正文拉取延迟与排队卡滞排障

- 现象：用户在前端查看刚收到的新邮件时，界面长时间停留在「正文同步任务已排队 后台归档 Worker 将拉取并保存完整原文」；后台实际上已拉取完成，前端也未能及时刷新（总耗时近 2 分钟）。
- 影响：所有未提前完成正文归档的新邮件，在用户即时点击查看时均受影响，严重影响开信体验。
- 根因：
    1. 【后端归档完成漏发实时通知】：`src/mail_core/blobs/archive.py` 在正文归档落库（`archive_complete` / `archive_in_progress`）写入 `OutboxEvent` 后，漏调了 `try_notify_outbox(session)`。API 进程收不到 PostgreSQL NOTIFY，导致前端 SSE 推送硬等满 30 秒超时才兜底发出（实测事件 20:25:01 落库，20:25:25 才推给前端）。
    2. 【任务优先级倒置与批量取锁堵塞】：
        - 新邮件到达后自动触发的正文归档被定为 `priority=60`（后台批次级），反而低于远程操作同步（`priority=40`）。
        - Worker 每次从数据库一次性批量锁定 5 个任务（`claim_batch=5`）。在前面有长耗时任务时，即使用户点击触发了最高优先级（`priority=10`）的正文任务，也无法抢占插队，必须等待前面的任务逐一跑完。
    3. 【远程操作未做 IMAP 批量合并】：积攒的多条已读同步（`mark_read`）在 Worker 内部使用 `for` 循环逐条发网络请求（5 次往返耗时 69 秒），未合并为单条 IMAP 批量指令（`UID STORE <uids> +FLAGS (\Seen)`）。
        同类位点清单：
    - `src/mail_core/sync/delta.py`、`src/mail_core/sync/reconcile.py` 等多处写入 `OutboxEvent` 亦存在漏调 `try_notify_outbox` 的情况。
- 测试缺口：
    1. 后端单测 `tests/mail_core/blobs/` 仅验证了 `OutboxEvent` 数据行写入，未断言是否触发了 `try_notify_outbox` / NOTIFY。
    2. 缺乏针对新邮件到达后正文抓取优先级高于远程操作同步的调度测试。
- 修复方向：
    1. 在 `src/mail_core/blobs/archive.py` 写入归档事件后补全 `try_notify_outbox(session)`，确保落库即推送。
    2. 将新邮件正文归档任务优先级从 60 提升至 20（高于远程同步的 40）。
    3. 将 Worker 每次取任务数量从 5 降为 1（或减少单次锁定），确保高优先级用户即时点击能被下一次 tick 立即调度。
    4. （可选）对积攒的同类型远程操作合并为单条 IMAP 批量指令提交，减少多余网络往返。
- 线索：
    - 最小复现脚本：`.scratch/repro_body_sync_queue_delay.py`
    - 真实追踪记录：邮件 ID `674aedee-30e9-42ce-9e16-dfc9c3a35985`（主题 `ご注文ありがとうございます W1535052453`），Outbox 事件 269415、269416 证实了 24 秒的 NOTIFY 缺失超时。
- 处理：未开
