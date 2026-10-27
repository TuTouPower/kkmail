# 2026-10-25 至 2026-10-26 提交整体审阅

本报告记录 `820781e5` 状态下仍存在的问题，不把中途已修复的问题重复列入结论。审阅未修改生产代码。

## 范围

- 时间范围：`2026-10-25T00:00:00+08:00` 至 `2026-10-27T00:00:00+08:00`。
- 基线：`4e48b16a1f0ae7f5a7a9bd0e5b00a0990a4a62c0`。
- 目标：`820781e5`，分支 `main`。
- 日期范围内有 372 个提交；基线至目标包含 375 个提交，其中 3 个提交编写于 10 月 24 日、随后随分支合入。整体 diff 包含这 3 个提交。
- 净改动：453 个文件，33,996 行新增，3,289 行删除。核对所有本地 refs 后，没有这两天尚未进入目标 HEAD 的其他提交。
- 审阅涵盖后端、前端、桌面端、同步与队列、迁移、备份恢复、部署、CI 和相关测试；按最终调用链检查交互，不按 commit 分割判断。

## 结论

发现 18 项问题：4 项 P1、14 项 P2。P1 表示应优先修复的核心功能或门禁阻断、并发数据保护失效；P2 表示有明确触发条件的功能缺陷、集成缺口或运维回归。

### R01 [P1] 增量同步和活动心跳绕过统一客户端，Cookie 登录下均被 CSRF 拦截

位置：`src/frontend/src/hooks/use_scope_sync.ts:26`、`:104`。

这两个 POST 直接使用 `fetch`，没有携带 `X-CSRF-Token`。正常浏览器及 Electron 使用 Cookie 会话，后端因此返回 403。进入列表、切换 scope、聚焦及手动增量同步都无法提交任务。403 的 `detail` 是对象，随后 `new Error(errData.detail)` 又将错误显示为 `[object Object]`。

独立验证：真实登录后调用同样缺头请求，得到 `403` 和 `csrf_error=true`；前端 hook 请求头检查也确认缺失。应使用既有 `postJson` / `apiRequest`。本项与审阅期间其他会话新增的 p053 重合，不另建 pending。

### R02 [P1] 单账号全量同步生成的请求 ID 超过数据库列上限，固定返回 500

位置：`src/mail_core/api/accounts.py:305`；`src/mail_core/mail/storage/models.py:452`。

`full:{account_id}:{uuid.uuid4().hex}` 长度为 `5 + 36 + 1 + 32 = 74`，但 `client_request_id` 在模型及迁移中均为 `VARCHAR(64)`。任何启用账号调用 `POST /api/accounts/{id}/sync` 都在插入请求时触发 PostgreSQL `StringDataRightTruncation`，设置页单账号和批量逐账号同步因此失败。

独立验证：真实 PostgreSQL、真实 API 调用得到 SQLSTATE `22001`。应使生成策略与存储约束一致，并覆盖正常成功路径。

### R03 [P1] CI 使用未安装后端依赖的 Python 导出 OpenAPI，后端门禁无法开始

位置：`.github/workflows/ci.yml:182`。

前一步把依赖安装到 `.venv/bin/python`，但没有激活虚拟环境或写入后续步骤 PATH；新步骤却运行 `python scripts/export_openapi.py --check`。在干净的 setup-python runner 中，系统解释器没有 FastAPI 等依赖，导入应用即失败，后续真实后端与 E2E 测试无法执行。

证据：工作流解释器路径核对；本地以排除 site-packages 的解释器执行相同导出入口，确认最先失败于 `ModuleNotFoundError: No module named 'fastapi'`。未在 GitHub runner 上启动工作流。应改用已经安装依赖的 `.venv/bin/python`。

### R04 [P1] 归档 claim_revision 只在内存中比较，旧 Worker 仍能覆盖新 claim

位置：`src/mail_core/blobs/archive.py:784`。

移除账号租约后，归档完成路径通过普通 `session.get` 读取状态，再比较 `claim_revision`；既没有锁住归档状态行，也没有带 revision 条件的 UPDATE。检查之后、提交之前，其他 Worker 可回收过期 claim 并递增 revision，旧 Worker 仍会将同一行写为 `archive_complete`、清空新 owner，并提交旧正文和附件。digest 锁只协调同一 Blob，不能保护该归档状态行。

独立验证：在生产解析调用处插入可控并发时序，让第二会话回收并重新认领；最终观察到 revision 已为 2，但 revision 1 的旧 Worker 仍返回 completed=1 并清除了新 claim。应在同一写入事务锁住状态行，或实现真正的 revision CAS 并原子保护全部派生写入。

### R05 [P2] 配额拒绝分支仍引用已经移除的 fencing 变量

位置：`src/mail_core/blobs/archive.py:749`、`:967`。

函数已删除 `fencing` 初始化及账号租约逻辑，但 MIME 预留失败、附件配额失败两个分支仍访问它。账号归档达到配额时抛出 `NameError`，暂停状态事务回滚，邮件继续停留在 `archive_in_progress`，无法正常展示配额暂停或及时恢复。

独立验证：让真实归档流程的 `reserve_quota` 返回 None，确认抛出 `NameError: fencing`，数据库状态仍为 `archive_in_progress`。应清理遗留租约代码并覆盖两种配额失败路径。

### R06 [P2] SyncRequestTarget 未接入 Worker，所有非空请求永久停留 queued

位置：`src/mail_core/mail/application/sync_requests.py:169`、`:217`。

目标创建为 `queued` 后，整个生产代码没有更新 target 状态、完成时间或错误的调用；Worker 也不消费 request_id / requested_generation。报告仅汇总这些不变化的 target，任务实际成功或失败都无法进入请求终态，设置页及未来任何轮询客户端均无法获得权威进度。

独立验证：创建请求、由真实 `handle_job` / `complete_job` 完成关联任务后，WorkerJob 已为 done，报告仍为 queued、queued_count=1、completed_count=0。应把 claim、续批、成功、终态失败和请求目标状态推进接通。

### R07 [P2] 前端收到 queued 后既不轮询也不订阅请求终态，按钮永久旋转

位置：`src/frontend/src/hooks/use_scope_sync.ts:44`。

hook 只保存请求 ID，之后从未使用它查询 `/sync/requests/{id}`，也没有相应 SSE 处理。`isSyncing` 只在初次 POST 直接返回终态或抛错时清零。因此即使 R01、R06 都修复，正常 202 queued 响应仍会让刷新按钮一直旋转并禁用。

独立前端验证：返回 queued 后推进测试时钟，确认没有请求状态 GET，isSyncing 仍为 true。应消费权威终态，并覆盖无 SSE、切 scope 和卸载场景。

### R08 [P2] full 标记未被执行层读取，全量同步仍沿用旧扫描游标

位置：`src/mail_core/mail/application/sync_requests.py:203`；`src/mail_core/worker/handlers.py:191`。

新全量入口只在 job payload 写 `full=True`。handler 调用普通文件夹发现函数时不传此标记；发现阶段再排 metadata 作业，既不建立扫描 generation，也不重置已有 checkpoint。IMAP 因而从旧 uid_next 开始，无法通过“全量同步”重新读取旧邮件元数据。技术设计 D10.3 明确要求重置扫描游标并保留本地意图。

独立验证：预置 full_scan_complete=True、uid_next=500，执行 full 请求及其 metadata 作业，实际 provider 收到的首个 cursor 仍为 `{uid_next: 500}`。应接入受租约保护的全量扫描生命周期。

### R09 [P2] 已发送、草稿、废纸篓及垃圾邮件视图同步了收件箱

位置：`src/frontend/src/lib/sync_scope.ts:27`、`:33`。

group/favorite 只有 inbox category 传 folder_role，其余 category 一律传 undefined；JSON 序列化将字段省略，后端 DeltaSyncIn 默认值又是 inbox。结果在 sent/trash 等视图点击同步只更新收件箱，当前视图保持陈旧。

独立前端验证确认 sent、trash 都省略 folder_role。应把这些真实角色原样传给后端，并仅将 unread 这类过滤视图映射至 inbox。

### R10 [P2] 合法省略 client_request_id 的增量请求触发 NameError

位置：`src/mail_core/api/mail.py:650`。

该字段提供默认工厂 `lambda: uuid.uuid4().hex`，但模块仅导入 `UUID`，没有导入 `uuid`。客户端按 OpenAPI 的可选字段契约省略该字段时，请求模型构造直接失败，无法获得服务端默认 ID。

独立验证：`DeltaSyncIn()` 稳定抛出 `NameError: uuid`。应修正导入并测试省略字段的合法请求。

### R11 [P2] 全局八连接限制从未接入真实 provider I/O

位置：`src/mail_core/providers/connection_slots.py:26`；`src/mail_core/providers/factory.py:98`。

新增 permit helper 只有定义和独立测试，生产调用链没有任何 import 或调用。IMAP 连接、Gmail 并行 metadata、Graph 请求、后台归档都不获取 permit，因此宣称的全局最多 8 个连接、归档最多 6 个连接及前台保留槽均不生效。多个 Worker 叠加 Gmail 每页最多 5 个并行请求即可超出该限制。

证据为调用点静态核对，未运行公网供应商压力测试。应将 permit 接入真实连接/请求生命周期，并用多进程计数服务器验证；仅直接测试 helper 不能证明集成生效。

### R12 [P2] Blob 恢复使用跨文件系统 rename，数据库成功后可能无法发布文件

位置：`src/mail_core/backup/package.py:1052`、`:1204`。

暂存目录建在备份包所在文件系统，目标 Blob 目录却允许位于另一个磁盘或 Docker volume。目标要求为空，所以正常首次发布走 `Path.replace`；跨文件系统时必然返回 EXDEV。此时 pg_restore 已提交，而目标 Blob 仍为空，finally 还会删除暂存内容；重试又受目标数据库非空检查阻断。

独立验证使用真实打包/校验/解包代码，模拟 pg_restore 成功并在最终发布处注入操作系统的 EXDEV，确认错误发生在 DB 恢复之后、目标无文件。未实际覆盖数据库或跨生产卷恢复。应在目标文件系统暂存，或提供跨卷安全发布与明确的部分成功恢复路径。

### R13 [P2] 新 Outbox 分发不再写 dispatched_at，保留期清理永久失效

位置：`src/mail_core/realtime/dispatcher.py:220`；`src/mail_core/realtime/outbox.py:157`。

新 dispatcher 只推进本地 publication sequence，不再写 dispatched_at；Worker 的 prune_dispatched 仍以 dispatched_at 非空且超过保留期作为删除条件。因此新事件即使已经成功交付也永远不会被清理，Outbox 表持续增长。

独立验证：实际订阅队列收到事件后，数据库 publication_seq 非空、dispatched_at 仍为空；即使把清理截止时间移至未来，prune_dispatched 仍删除 0 行。应按新发布/重放协议更新保留期清理，而非恢复依赖单进程消费的旧语义。

### R14 [P2] Outbox 模型和迁移不一致，现有 schema drift 门禁已失败

位置：`src/mail_core/mail/storage/models.py:351`、`:362`；`src/mail_core/db/alembic/versions/20261026_0022_outbox_publication_seq.py:54`。

迁移创建 ix_outbox_unassigned，但模型没有登记；模型又同时声明 publication_seq 的列级 unique=True 和显式唯一 index，迁移只有后者。Alembic 因而检测到删除未登记索引及新增唯一约束，既有零 drift 门禁无法通过。

独立运行 `test_orm_schema_drift_and_negative_detection` 已失败，并输出这两项确切差异。应使模型与迁移一致，保留需要的 PostgreSQL 索引登记，避免未来自动迁移误删索引。

### R15 [P2] 阅读器的迟到请求检查使用旧闭包，仍会污染下一封邮件

位置：`src/frontend/src/components/MessageReader.tsx:112`、`:120`、`:123`。

请求开始时的 selected 与 targetMsgId 都被同一次闭包捕获，切换邮件并不会改变旧闭包中的 selected。三个检查因此始终认为请求仍属于当前邮件；A 请求迟到失败会写入 B 的 syncError，并可能清除 B 正在提交的状态。

独立前端验证：A、B 都是未归档邮件，A 请求未完成时切到 B，再让 A 失败，B 页面出现 A 的错误。现有 p048 测试切到已归档邮件，且仅检查默认错误文本，未覆盖该场景。应使用当前选中邮件 ref、请求 generation 或取消信号隔离结果。

### R16 [P2] 组合修改账号同步偏好与分组时，取锁顺序反转导致数据库死锁

位置：`src/mail_core/mail/application/accounts.py:243`；`src/mail_core/accounts/service.py:116`。

新增 prior_sync_enabled 查询先锁 Account；如果同一 PATCH 还提交 group_id / clear_group，后续 update_account 再取 sidebar advisory lock。布局保存等组织事务遵守 sidebar → Account 的相反顺序。两者并发时，一个等待组织锁，另一个等待账号行，PostgreSQL 会中止其中一笔请求。

独立验证：两个真实 PostgreSQL 会话分别执行组合 PATCH 应用服务和 sidebar → Account 事务，稳定捕获 SQLSTATE `40P01`。应让所有组合更新保持组织锁在前，避免只因新增偏好快照读取破坏既有锁序。

### R17 [P2] 新接口及 v2 SSE 契约未迁移既有测试，完整后端门禁仍不可用

位置：`tests/mail_core/test_sse_medium_remaining.py:85`、`:129`；`tests/mail_core/test_outbox_listen.py:37`；`tests/mail_core/test_message_detail_readonly.py:66`。

SSE 生产 `_ReplayPlan` 已新增 cursor_seq，但两个队列隔离测试仍只传两个参数；三个非法游标测试的 fake build_replay 仍要求已删除的 malformed 关键字；LISTEN 测试把新 `v2:epoch:seq` 字符串传给 int。正文异步同步、任务完成和归档 claim 测试也保留旧返回值、旧 fake Session 或未配置 claim_revision 的替身；两个迁移测试仍硬编码旧 head `20261025_0021`。这些用例没有验证到新行为便报错，不能支撑修复已完成的结论。

证据：完整后端运行在中断前已有 16 failed，其中 R02、R14 是实际功能/结构缺陷，其余失败需逐项迁移测试契约并保留原行为覆盖。分段补跑还确认 `test_storage_package_exports_every_orm_model` 失败，生产存储公共入口遗漏 OutboxPublicationState、SyncRequest、SyncRequestTarget、AccountSyncActivity；该项应补齐导出，不能缩小测试期望。完整运行停在 `test_malformed_last_event_id_emits_resync_hint`，该测试仍等待旧 reason，当前实现返回 epoch_mismatch。本机 TestClient 流式读取没有结束，本轮已主动中断并由测试运行时回收隔离数据库。应修正替身与断言、让流式测试有可控结束条件，并重新执行完整门禁；不能通过排除失败用例宣称全套通过。

### R18 [P2] provider 初始化失败不再写入归档错误，阅读器一直显示排队

位置：`src/mail_core/blobs/archive.py:698`、`:318`。

原错误恢复 helper 接收异常并写入 MessageArchiveState.last_error；新 `_release_fencing_claims` 仅清 owner、恢复 pending，丢弃 build_provider 异常。凭据读取、连接配置或 provider 初始化失败时，WorkerJob 虽会失败重试，详情 API 的 archive_has_error 却保持 false。后台最终耗尽重试后，阅读器仍显示正文排队，无法展示失败及立即重试入口。

独立验证：通过真实应用服务入队，令归档 provider 构造抛出异常；确认状态回到 archive_pending、last_error 为空，详情 archive_has_error=false。应保留脱敏错误及对应状态事件，并对照 Worker 终态确保阅读器能进入可重试失败状态。

## 验证证据

以下命令均从仓库根目录执行，使用项目现有测试运行时及隔离数据库；复现代码仅写入被 gitignore 的 `.scratch/commit_review/`。

- 前端现有套件：`npm --prefix src/frontend test -- --run`，45 个文件、394 项测试通过；OpenAPI TypeScript 一致性和 CSS token 检查通过。
- 桌面基础套件：`npm --prefix src/desktop test`，通过；Electron OAuth 集成因未提供专用测试入口而按入口规则跳过，不等于真实 Electron 集成通过。
- 后端相关既有测试：`scripts/run-mail-core-tests.sh run -k 'test_sync_requests or test_outbox_publication_order or test_on_demand_body_sync or test_job_successor_atomicity' --no-cov`，19 passed。
- 后端独立缺陷复现：`scripts/run-mail-core-tests.sh run .scratch/commit_review/test_review_evidence.py -k test_review_ --no-cov`，11 passed。这里的通过表示用例确认缺陷能够发生，不表示修复通过。
- 前端独立缺陷复现：`src/frontend/node_modules/.bin/vitest run --config .scratch/commit_review/vite.config.mts`，3 passed，分别确认缺 CSRF/不消费终态、角色遗漏、迟到错误污染。
- schema drift 专项：`scripts/run-mail-core-tests.sh run -k test_orm_schema_drift_and_negative_detection --no-cov`，1 failed，确认 R14。
- 后端 live OpenAPI 导出：`.venv/bin/python scripts/export_openapi.py --check`，通过，39 个路径与已提交 schema 一致。
- 整体 diff 的 `git diff --check 4e48b16a 820781e5` 通过。
- 全量后端：`scripts/run-mail-core-tests.sh run --no-cov`，收集 978 项；中断前 782 passed、16 failed、2 skipped，178 项未完成。在 SSE 流式用例停住后主动 SIGINT，隔离测试运行 `63f3894a573d438fa2a73d2548f55e88` 已确认清理。汇总位于 `.scratch/test_runs/63f3894a573d438fa2a73d2548f55e88/test_summary.json`；两项 skip 均为显式未启用的 Electron OAuth 集成。
- 剩余测试分段补跑：170 passed、10 failed；其中 8 个用例与前轮重复。按 nodeid 合并两轮证据后为 949 passed、21 failed、2 skipped，另有 6 个 SSE 流式用例未完成或未执行。汇总：`.scratch/commit_review/backend_combined_summary.json`。分段运行 `a5cb2a372634445c81f584dc35b02e63` 已确认清理；不将分段结果等同于全套通过。

分段运行中 `test_pymap_fallback_passes_private_passfile_and_cleans_it_up` 的失败属于已知本机环境干扰：`~/.local/bin/rm` 包装器通过 `/usr/bin/env python3` 启动，被测试 PATH 中的 fake python3 截获，测试 passfile 没有清理。此前审阅的 `review_20261026_005019_full_repository/review_evidence.md` 已记录同一原因。本次未修改或绕过包装器；该失败单列，不作为新增生产代码缺陷。残留测试文件为 `.scratch/imap-pass.OZMGrU`。

本次未执行生产写入、部署、发布、真实供应商 OAuth、供应商公网负载测试、严格桌面打包或真实全栈浏览器 E2E。R03 为工作流静态解释器核对及本地缺依赖复现，R11 为生产调用点核对；R12 的跨文件系统失败采用故障注入，未伪称真实跨卷恢复通过。

## 修改边界

仅新增本报告及 `.scratch/commit_review/` 复现材料。审阅期间其他会话新增的待办保持原样；未修代码，未提交或合并任何改动。
