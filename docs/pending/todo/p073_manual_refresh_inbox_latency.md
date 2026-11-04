# p073 手动刷新收件箱被账号级全文件夹串行同步拖慢

- 现象：2026-11-04 22:15:55 CST 验证邮件到达 Outlook 服务端；22:15:58 用户在收件箱点「立即同步」，邮件直到 22:16:50 才落库/出现，请求 22:16:53 才终态，按钮空转 55s。邮件本身不慢——点击时服务端已有该邮件 3 秒。
- 影响：账号视图（含收件箱）手动刷新耗时等于「文件夹发现 + 全部文件夹 delta 串行」；本次 8 个文件夹共 55s。文件夹越多、单个 delta 越慢，延迟线性放大。已确认同类位点：新账号首次初始化的 metadata 基线扫描同样按文件夹顺序入队、无 inbox 优先（`src/mail_core/sync/engine.py:418-423`）；delta 因账号租约冲突重排时硬编码 priority 60，会丢掉 inbox 高优先级（`src/mail_core/sync/delta.py:373-379`）。Graph 账号无 IDLE（`idle_watcher.py:386` 仅 provider=="imap"），后台发现依赖 20 分钟轮询，用户手动刷新是主要感知手段，影响更明显。
- 根因：代码调度问题，非邮件服务器慢。`sync_account_folders` 每次账号级 delta 先同步目录（本次 12.5s），随后按 provider 返回顺序为全部可同步文件夹一次性入队 `SYNC_FOLDER_DELTA`，priority 固定 60（`engine.py:386-403`）；账号租约使同账号 delta 串行（`delta.py:369`），收件箱恰好排第 6，14:16:11 入队、14:16:50 才执行完。前端账号视图等待全部 target 终态才失效列表（`MessageList.tsx:532-570`），因此整体感知等于最慢文件夹。同期叠加环境负载：14:10:18 全文件夹 patrol 触发的 17 个 delta 单任务执行 6~8 分钟，占用连接槽，属暴露放大因素而非邮件或正文问题。
- 测试缺口：`tests/mail_core/test_sync_mode_policy.py` 等只种一个 inbox 文件夹，从不覆盖多文件夹的入队顺序与优先级，故 inbox 排第 6 无测试可红；baseline/metadata 入队路径同样无顺序断言；`delta.py` lease-busy 重排的 priority 保持也无覆盖。应补后端测试：种 inbox + 多个有 baseline 的文件夹，断言 inbox delta 的 priority 严格低于其他文件夹且 claim 顺序 inbox 先；覆盖全量/metadata 路径；覆盖 lease-busy 重排后 inbox 优先级不丢失。前端补充验证：收件箱 delta 落库触发 `message.upserted` 后列表即可见，不以整个账号请求终态为可见前提。
- 线索：`.scratch/bug_inbox_refresh_latency/timeline.md`；生产证据见 `sync_requests` id `006196f0-0ca3-43e4-9842-97fe87656a58` 与对应 `worker_jobs` 时间戳。
- 处理：未开
