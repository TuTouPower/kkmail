---
pid: "p073"
slug: "manual_refresh_inbox_latency"
status: "closed"
resolution: "resolved"
reason: "已在 Adoption A21 解决"
fix_ref: "Adoption-A21"
---
# p073 手动刷新收件箱被账号级全文件夹串行同步拖慢

- 提出日期：2026-11-04
- 闭环日期：2026-11-09
- 现象：2026-11-04 22:15:55 CST（14:15:55Z）验证邮件到达 Outlook 服务端；22:15:58 CST 用户在收件箱点「立即同步」，邮件直到 22:16:50 CST（14:16:50Z）才落库/出现，请求 22:16:53 CST（14:16:53Z）才终态，按钮空转 55s。邮件本身不慢——点击时服务端已有该邮件 3 秒。
- 影响：账号视图（含收件箱）手动刷新耗时等于「文件夹发现 + 全部文件夹 delta 串行」；本次 8 个文件夹共 55s。文件夹越多、单个 delta 越慢，延迟线性放大。已确认同类位点：新账号首次初始化的 metadata 基线扫描同样按文件夹顺序入队、无 inbox 优先（`src/mail_core/sync/engine.py:418-423`），且 metadata 分页续页/租约冲突/限流/容量路径回落 priority 50（`engine.py:510/656/680/763`），inbox 跨页也会被其他文件夹 metadata 插队；delta 因账号租约冲突重排时硬编码 priority 60，会丢掉 inbox 高优先级（`src/mail_core/sync/delta.py:373-379`）。Graph 账号无 IDLE（`idle_watcher.py:386` 仅 provider=="imap"），后台发现依赖 20 分钟轮询，用户手动刷新是主要感知手段，影响更明显。
- 根因：代码调度问题，非邮件服务器慢。`sync_account_folders` 每次账号级 delta 先同步目录（本次 12.5s），随后按 provider 返回顺序为全部可同步文件夹一次性入队 `SYNC_FOLDER_DELTA`，priority 固定 60（`engine.py:386-403`）；账号租约使同账号 delta 串行（`delta.py:369`），收件箱恰好排第 6，14:16:11Z（22:16:11 CST）入队、14:16:50Z（22:16:50 CST）才执行完。前端账号视图等待全部 target 终态才失效列表（`MessageList.tsx:532-570`），因此整体感知等于最慢文件夹。同期叠加环境负载：14:10:18Z（22:10:18 CST）全文件夹 patrol 触发的 17 个 delta 单任务执行 6~8 分钟，占用连接槽，属暴露放大因素而非邮件或正文问题。
- 测试缺口：`tests/mail_core/test_sync_mode_policy.py` 等只种一个 inbox 文件夹，从不覆盖多文件夹的入队顺序与优先级，故 inbox 排第 6 无测试可红；baseline/metadata 入队路径同样无顺序断言；`delta.py` 与 `engine.py` metadata 续页/lease-busy/限流重排的 priority 保持也无覆盖。应补后端测试：种 inbox + 多个有 baseline 的文件夹，断言 inbox 任务 priority 数值严格小于其他文件夹（同事务 `created_at` 并列，不能只断言认领顺序）；覆盖全量/metadata 分页续页路径；覆盖 delta 与 metadata 各重排路径后 inbox 优先级不丢失。前端补充验证：收件箱 delta 落库触发 `message.upserted` 后列表即可见，不以整个账号请求终态为可见前提。
- 线索：`.scratch/bug_inbox_refresh_latency/timeline.md`；生产证据见 `sync_requests` id `006196f0-0ca3-43e4-9842-97fe87656a58` 与对应 `worker_jobs` 时间戳。
- 残留（t074 不覆盖）：文件夹发现 12.5s 仍在收件箱前，前端仍等全部文件夹完成后终态/停止旋转；因此按钮空转时长不会完全消失。后续可选：手动刷新先入队 folder-scoped delta 绕开发现耗时，或缓存/并行目录发现。
- 处理：fix_ref=Adoption-A21；resolution=resolved；reason=已在 Adoption A21 解决
    - 解耦方案：
        1. 在 `create_sync_request` / `resolve_sync_targets` 中，对已有有效收件箱的账号，主刷新请求的目标直接解析为收件箱文件夹，入队 `SYNC_FOLDER_DELTA`（priority=20，前台交互优先级），仅以收件箱同步完成作为主刷新请求的终态判定依据。
        2. 全目录发现（`SYNC_ACCOUNT_FOLDERS`）与其它非收件箱文件夹的同步拓扑拆分为独立的后台任务请求（`background=True`，priority=60），由主请求携带 `background_request_id` 关联追踪，独立调度、独立结算。
        3. 若为新账号或收件箱角色失效，回退至必要目录发现流程，不产生解耦后台请求。
        4. 前端 `api/sync.ts` 与 `MessageList.tsx` 在收件箱终态后立即解除 loading 旋转并失效/刷新邮件列表；后台任务在状态栏独立监控展示进度；若后台次要文件夹同步失败，执行错误隔离，不覆盖收件箱已成功的状态。
    - 测试覆盖：
        - `tests/mail_core/test_sync_inbox_first.py`：新增 `test_a21_inbox_settles_independently_and_background_syncs_siblings`、`test_a21_background_folder_failure_is_isolated_from_inbox` 和 `test_a21_new_account_without_inbox_runs_discovery`，覆盖多文件夹下收件箱优先结算、后台任务独立完成、错误隔离与新账号回退。
        - `src/frontend/src/api/sync.test.ts`：覆盖 `hasActiveBackgroundSync`、`backgroundSyncFailureDetail` 与 `pollBackgroundSync`。
    - 契约说明：
        - `SyncRequestOut` 扩展 `inbox_ready`、`background_request_id`、`background_state` 和 `background_errors` 字段。
        - OpenAPI 规范（`schemas/openapi.json`）与前端生成类型（`schema.ts`）已同步更新。
