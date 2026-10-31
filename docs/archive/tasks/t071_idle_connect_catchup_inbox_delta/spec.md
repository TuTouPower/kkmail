# Task spec

## 背景

生产复现（p070）：一封 Gmail 收据的服务器到达时间（IMAP INTERNALDATE）为 `2026-10-31T08:05:19Z`（本地 16:05:19），本地 `messages.created_at` 却是 `2026-10-31T12:10:57Z`（本地 20:10:57）。16:05 之后到 20:10:47 之间没有任何自动收件箱 `SYNC_FOLDER_DELTA`，最终由用户手动同步（`sync_requests.trigger=manual`）拉入。Worker 在 19:43:54 重建后也没有补拉。

根因是 t061 IDLE 通道缺少建连补偿：`IdleWatcherManager._watch_loop` 在断线后重建会话，`open_idle_session` 的 `SELECT INBOX` 只取得当前 EXISTS/UIDNEXT 快照，IDLE 仅上报订阅之后的新变化；代码建连后直接进入 `idling`，从不入队补偿 delta。断线或 Worker 重启窗口内到达的邮件因此不会再产生事件；同时 t057 轮询会跳过 `held` 账号，形成静默无限期滞后。

## 契约区

### 范围

- 每次 IMAP IDLE 会话成功建立后，为该账号收件箱入队一次补偿 `SYNC_FOLDER_DELTA`，随后进入 `idling`；覆盖 Worker 启动后的首连、断线/退避后的重连、凭据变更或席位重新获取后的重建。
- 补偿任务沿用既有去重键 `delta:{account_id}:{folder_id}`：若同键任务已处于 pending/claimed，仅合并，不产生并行的重复执行。
- 补偿 delta 必须继续走既有流水线：基线门禁、账号租约、fencing 与正文归档行为不变；不得因补偿任务跳过或绕过这些约束。
- 补偿入队失败不得终止 watcher 线程、不得把账号标记为 `failed`，也不得影响后续重连与 IDLE 事件处理。
- 不具备 IDLE 能力、永久认证失败或处于阻塞退避的账号不产生补偿任务，继续保持 t057 轮询兜底。

### 非范围

- 不改变 IDLE 席位配额、排序、滞回逻辑。
- 不恢复 held 账号的周期性轮询；不新增按固定间隔的收件箱轮询。
- 不处理 Graph 账号（其收件箱仍由 t057 轮询覆盖）。
- 不改 UI、不改手动同步入口、不为历史遗漏邮件提供独立回填命令。
- 不改变文件夹 STATUS 巡检排除 inbox 的既有策略。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：Worker 启动后 IMAP 账号首次成功建立 IDLE 会话时，系统为该账号收件箱入队且仅入队一个待执行 `SYNC_FOLDER_DELTA`（去重键为该账号与该收件箱），随后账号进入 `idling` 并可被周期轮询跳过。
- [ ] AC-002：IDLE 会话因断线/服务端 BYE 结束并重连成功后，系统再次入队收件箱补偿 delta；若同去重键任务已 pending/claimed，则合并到既有任务，不出现两个可并行执行的同键任务。
- [ ] AC-003：无活动 IDLE 会话期间到达收件箱的邮件，在重连补偿 delta 执行后进入本地数据库，无需用户手动同步；判定依据是该邮件 `remote_id` 对应的 `Message` 行存在且 `sort_time` 为服务器到达时间。
- [ ] AC-004：服务器不支持 IDLE 或认证永久失败的账号不产生补偿任务，账号不因此被标记 `failed`，收件箱继续由 t057 轮询同步。
- [ ] AC-005：补偿入队抛出异常时，watcher 线程继续运行，账号状态不进入 `failed`，后续 IDLE 变化事件仍能入队 delta。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。AC-001/002/004/005 使用 `IdleWatcherManager` 与假 IDLE 会话及测试 PostgreSQL 断言任务行、去重与状态；AC-003 用 `MemoryProvider` 构造基线后“断线期间”新增邮件，再执行补偿 delta 并断言本地消息行。

## 上下文区

- 来源：`p070`（2026-10-31 生产数据核实：`messages.id=668406d2-b10d-49fb-9b7e-03eb8b846e55`，`messages.created_at=2026-10-31T12:10:57Z`，`sort_time=2026-10-31T08:05:19Z`；手动同步请求 `2dcc95a5-fa38-4d77-b622-51ad2686b68d`；`.scratch/repro_idle_reconnect_gap.py` 复现重连后补偿入队数为 0）。

### 有意不测

- 真实 Gmail/服务端的 28 分钟 IDLE 主动重入与网络半开检测：依赖真实供应商时序，使用假会话覆盖断线与重连路径。
- 连接建立后毫秒级 SELECT→IDLE 订阅窗口内的极端竞态：不属于本次确认的断线窗口缺陷，不构造不稳定测试。
- Graph 账号：本期不改其轮询路径。

### 测试策略

- `IdleWatcherManager` 层：假会话首连、断线重连、pending 任务合并、无 IDLE 能力降级、入队异常隔离；断言 `worker_jobs` 行与 watcher 状态。
- 同步引擎层：`MemoryProvider` 基线完成后模拟断线窗口新增邮件，执行补偿 `sync_folder_delta`，断言 `Message` 入库与 `sort_time`。
- 回归：既有 t061 IDLE 选择、配额、轮询跳过与 STATUS 巡检测试保持通过。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：连接抖动时补偿任务可能频繁入队，增加 delta 扫描；由既有去重键、退避与单条 IDLE 连接约束，最坏为每次重连一次增量检查。
- 风险：补偿任务与 IDLE 事件任务同时争用账号租约；沿用既有 `lease_busy` 后继调度，不新增锁路径。
- 回退：本变更仅影响 IDLE watcher 的建连副作用，可回退为不补偿；同步流水线与数据模型不变，无迁移。

### 依赖与约束

- 依赖 t061 已完成的 IDLE watcher、去重键与 t057 轮询跳过逻辑。
- 不新增运行时依赖；不改变集中配置项语义。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：t061 章节补充“IDLE 建连/重连后入队一次收件箱补偿 delta”的收敛语义。
- `docs/specs/mail_sync_and_storage.md`：t061 契约补充建连补偿、去重合并与降级边界。
