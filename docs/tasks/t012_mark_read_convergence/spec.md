# Task spec

## 背景

p016 已确认“全部已读”出现反复未读与角标不一致：写回首批完成后丢失续跑，旧远端同步覆盖尚未收敛的本地读状态，flag-only delta 又在消息状态 flush 前计算统计。三处共同破坏本地操作到远端确认的闭环，应作为同一修复交付，不能仅增加点击次数或清缓存。

## 契约区

### 范围

- 写回 worker 的实际 claim → handler → complete 生命周期：首批后续跑、限流/瞬时错误延迟重试、运行期间新增操作与 CAS 后最新意图续跑。
- metadata upsert 与 delta flag patch 对最新本地 is_read / is_flagged 意图的字段级保护与远端确认后的正常同步。
- 受影响文件夹未读统计与消息状态在同一事务中的一致性；统计 API 及“全部已读”相关界面行为回归。
- 对既有 orphan pending 写回和失真统计提供可重复、可限定账号的恢复路径；实施与验收只操作隔离测试数据。

### 非范围

- 不增加文件夹导航或查询 scope；新增目录行为归 t008。本 task 保持现有账号、角色、旗标筛选范围。
- 不修复 QQ 非收件箱目录 UID SEARCH 返回 NO、邮箱授权或 MIME/报头解析，不调整服务商协议语义。
- 不重写全套调度系统，不提高批次上限来绕过续跑问题，不清空操作队列、不重置全账号游标、不删除邮件或重新导入邮箱。
- 不在 task 创建阶段执行生产恢复；外部发布及真实邮箱写操作不在本次创建授权内。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：对当前筛选范围内超过一批的未读邮件执行一次“全部已读”后，真实 worker 生命周期能自动处理后续批次；在 provider 可用且无新邮件或后续反向操作时，原目标邮件最终在本地与远端均为已读，不因首批完成留下无调度的 pending；测试不得直接手动二次调用 push 代替产品调度。
- [ ] AC-002：写回遇到瞬时错误或限流后保留正确待重试状态，worker 在既有退避/Retry-After 约束到期后自动重试；未来任务不被当前 claimed 任务吞掉，也不被其他立即到期操作无限推迟；永久失败与重试上限保持现有明确终态，不形成紧密空转。
- [ ] AC-003：写回执行期间新增已读、未读、旗标或删除意图，及同实体 CAS 检出较新 revision 时，后续意图仍获得持久化执行机会；成功确认旧 revision 不会误将较新操作标为 done，最终按最新意图收敛，重放不造成重复副作用。
- [ ] AC-004：本地已读/未读或旗标意图处于待处理、推送中，或旧同步快照跨越写回完成边界时，metadata upsert 与 flag delta 均不能用较旧远端值覆盖最新本地意图；未被本地修改的主题、地址、正文关联等数据继续正常同步，不因保护读状态而冻结整封邮件。
- [ ] AC-005：没有未收敛本地意图时，远端真实的后续已读/未读及旗标变化仍能同步到本地；保护机制不永久锁死已经完成或明确失败的字段，并保持不同账号、实体、字段间隔离。
- [ ] AC-006：已有统计行及首次创建统计行两种场景中，提交读状态变化后，新 session 查询到的实际未读、受影响文件夹 FolderStats、对应统计 API 一致；覆盖读转未读、未读转已读与多位置邮件。重复无变化 delta 不引入计数漂移。
- [ ] AC-007：已有 pending 但没有活跃写回任务的账号，以及消息未读与缓存统计已失配的账号，经过限定该账号的恢复路径后能继续写回并恢复一致计数；重复恢复不重复创建等效活跃任务、不更改其他账号、不重置同步游标、不重放已完成或永久失败操作、不破坏邮件身份与附件关联。
- [ ] AC-008：界面执行“全部已读”后，经统计刷新或 SSE 更新得到的列表、侧栏未读数与已提交数据一致；无新增邮件时后台同步不使本次目标邮件重新变未读，不会因错误零角标禁用仍有合法目标的操作；合法新来信仍显示未读。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

全部 AC 可自动测试。使用隔离 PostgreSQL、可控时钟与 provider Stub 验证实际生产入口；界面行为通过组件或浏览器测试配合统计 API 验证，不需要真实 QQ 凭据。

## 上下文区

- 来源：p016（2026-10-22 核实；转办后见 docs/archive/pending/p016_mark_all_read_sync_convergence.md）。运行态只读证据：2504\*\*\*@qq.com 收件箱 1463 封、实际未读 66、缓存未读 40，66 条 mark_read pending 且 attempts=0，0 个活跃写回任务；3 个 done 批次各完成 20 条。前轮隔离复现六组场景通过，未操作真实邮件；本次再次核对生产代码，根因仍存在。effective status 无等价 task；t008 仅存在相关文件交叠。

### 有意不测

- 真实 QQ 邮箱写回与长期在线配额：不使用用户凭据制造副作用；provider Stub 及现有 IMAP/Gmail/Graph 写回契约覆盖适配边界。
- 新文件夹范围与非收件箱 UID SEARCH 错误：不属 p016 已确认根因；仅回归已有过滤边界，不借本 task 扩大功能。

### 测试策略

- TDD：先把下述最小复现迁为触达生产逻辑的失败测试，再修复；保留仍有效旧测试，不把旧预期改成错误实现的输出。
- 用已有 mark_all_messages_read、claim_jobs、handle_job 和真实 complete 路径测试 26 条操作，基线应复现 20 done + 6 pending + 0 活跃任务；修复后靠 worker 后续调度自然排空。测试必须带 claimed 同键 WorkerJob，禁止只直接调用 push_remote_operations。
- 用 Stub provider 和可控时钟覆盖正常余量、同轮立即任务与未来重试共存、Timeout、429/Retry-After、永久错误、重试预算、运行期间新增操作与 CAS 更新、worker 中断后的可恢复执行；确认既有租约、fencing、ownership 与幂等约束不被放宽。
- 基线六场景：首批续跑丢失；剩余 6 条旧 flag delta 后实际未读 6、缓存 0；metadata 覆盖 pending read；delta 覆盖 pending flag；瞬时错误重试丢唤醒；CAS 更新丢后续唤醒。前轮 .scratch/unread_repro/ 产物当前已不存在，以上步骤与结果保留在 p016 和本 spec，实施时重建为正式回归，不把 scratch 文件作为依赖。
- 字段级交错矩阵：read/flag × metadata/flag delta × pending/in_progress/完成边界旧快照；同时验证后续合法远端变化、不相关元数据正常更新、账号隔离与实体隔离。
- 预建 FolderStats，在生产 autoflush=False 会话提交后另开 session，以 SQL 实数比对缓存和统计 API；覆盖双向状态变更、多位置、首次统计创建、无变化重放及“先前已漂移”恢复。
- 结合现有 test_message_mutations_api.py、test_flag_convergence.py、test_delta_flag_patch.py、test_remote_ops_reconcile.py、test_folder_stats_race.py 增补真实 PostgreSQL 测试；全程使用 disposable test DB，禁止测试连接生产 DB。
- 前端 MessageList 与 Sidebar 回归一次全部已读、统计刷新、SSE、零计数禁用与合法新来信；生产前端只有为满足本 task 行为确有必要时修改。最终执行 docs/blueprint/testing.md 对应门禁。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

无新增外部契约。既有 provider 写回接口、Retry-After、CAS/revision、账号租约和统计接口为基线；修复设计须显式证明旧快照跨越写回确认边界时的顺序保护，不以仅检查当前 pending 状态替代此验证。

### 风险与回退

- 风险：全局改变 enqueue_job 去重可能影响其他后台任务；只保护 pending 会遗漏写回完成后才提交的旧快照；将已完成字段永久锁住会阻断真实远端变化；恢复队列若直接回放终态操作可能重复副作用；统计 flush 与锁顺序改变可能扩大死锁窗口。
- 回退：回退本 task 执行 commit 恢复旧行为；恢复前保留待处理操作、revision 与统计核对结果。若实现涉及持久化字段，必须附迁移、备份与可验证回退，禁止删除用户数据；不得把回退代码等同于撤销已经成功的远端已读写入。

### 依赖与约束

- 无硬依赖。t008 可能修改 mutations、queries 和相关测试，实施建议串行或在集成前复核交叠；不等待 UI 主题、图标或编号 task。
- 并发与跨协议收敛风险使用 full review。遵守本地优先、字段级 latest intent、CAS/revision、账号级租约、fencing、worker ownership 与 provider 幂等约束。
- 不把永久失败静默恢复为已完成，也不在恢复中覆盖用户较新意图；诊断输出继续脱敏，不包含凭据或邮件正文。
- 交付提供恢复说明与隔离验证；真实环境恢复、部署和邮箱写回须遵循实际实施阶段授权，不在创建阶段执行。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：写回任务续跑与恢复、本地意图和入站同步之间的数据流。
- `docs/blueprint/conventions.md`：字段级收敛顺序及统计聚合前可见性约束。
- `docs/blueprint/decisions.md`：旧快照与本地意图的仲裁、持久化后续唤醒方案及选型理由。
- `docs/blueprint/testing.md`：真实 claimed 生命周期、字段交错和统计一致性回归要求。
