# kkmail 审阅问题与 p045–p052 修复计划

- 制定时间：`2026-10-26T01:10:44+08:00`。
- 代码核对基准：`55a54fb3fb37460671cb3b9bb07a69c08131390f`。相对审阅终点 `6f6605b6`，新增提交只调整 pending 文档，相关生产实现未变化。
- 来源：[审阅报告](review_report.md)、[验证证据](review_evidence.md)、[p045](../../pending/todo/p045_sidebar_search_click_outside_auto_hide.md)、[p046](../../pending/todo/p046_sync_button_spin_and_remove_banner.md)、[p047](../../pending/todo/p047_incoming_mail_sync_latency.md)、[p048](../../pending/todo/p048_message_reader_already_archived_race.md)、[p049](../../pending/todo/p049_settings_header_cleanup_and_sidebar_toggle_relocate.md)、[p050](../../pending/todo/p050_sidebar_settings_button_background_style.md)、[p051](../../pending/todo/p051_sidebar_account_folder_order_and_indent.md)、[p052](../../pending/todo/p052_ui_reference_overlay_prod_and_shortcut_setting.md)。
- 目标：修复计划内行为，恢复相关门禁，完成隔离验证后统一合入。目标版本尚未指定。
- 状态：**计划，未实施**。本次授权仅为编写计划，不创建分支/worktree，不运行修复，不创建 commit 或 merge。
- 执行方式：按用户明确要求采用**直接 Git 分支、独立 worktree、多 Agent、多 commit**。不使用 task、attempt、task-run、task-work、task-integrate 流程，不创建 task/spec 目录，不套用单 task 一个实现 commit 的限制。

## 1. 范围与完成定义

### 1.1 明确排除

本计划不处理 **P1-06（桌面 CI 资产依赖）**、**P2-05（健康指标匿名访问）**。原审阅记录保留，不改为已解决，不附带修复相应 CI job 或指标路由鉴权。

排除的是修复范围，不是暂停其他验证。桌面基础测试仍需执行；API codegen 仍会忠实包含现有健康路径。最终报告不得宣称整个仓库 CI 全绿，因为 P1-06 保持未处理。

### 1.2 覆盖矩阵

F00–F12 是本文内部工作包标签，**不是 task ID**。C01 等是各分支上的建议 commit 次序，实际 SHA 在执行记录中填写。

|来源|目标行为|负责工作包|
|---|---|---|
|P1-01|备份包成员、目标目录、链接无法越界写入|F02|
|P1-02|同一实际源库不因用户名/连接别名变化而被恢复覆盖|F02|
|P1-03|去重入队与完成交错不丢唤醒|F03|
|P1-04|SSE 在线与重连均不漏较晚提交的小 ID 事件|F07|
|P1-05|provider 原始异常、异常链与 token 不进入日志|F01|
|P2-01|后继载荷、优先级、执行时间与周期计数可靠传递|F03|
|P2-02|共享邮件读状态变化刷新所有受影响文件夹统计|F05|
|P2-03|只删除一个位置也刷新统计和失效事件|F05|
|P2-04|IMAP 废纸篓使用真实 remote_id|F05|
|P2-06|合法长任务期间进程健康心跳持续更新|F06|
|P2-07|成功同步指标读取生产合法 done 状态|F06|
|P2-08|OpenAPI JSON/TypeScript 与生产代码一致|F00；各 API 变更分支持续维护；F12 最终复核|
|P2-09|OAuth 返回状态处理通过 lint 且保留既有行为|F09|
|P2-10|先验证原生 dialog 真实复制，再修复确认的问题|F09|
|p045|账号列表及各组搜索支持外部点击/失焦收起|F04|
|p046|列表轻量增量、设置全量、同步状态旋转、成功横条移除|F10|
|p047|分段测量、优先级调整、前台活跃触发、冷热轮询、全局连接上限|F03/F05/F06/F07 提供基础，F10 交付场景化同步|
|p048|按需正文同步幂等；后台归档完成竞态自动恢复详情|F08|
|p049|移除设置顶栏及返回按钮，侧栏按钮进入设置导航|F09|
|p050|设置按钮常态弱化，hover/active/focus 状态明确|F04|
|p051|收件箱在未读项前、文件夹/状态行按几何基准缩进|F04|
|p052|生产包提供序号浮层，支持本地快捷键配置与开关|F11|

计划覆盖 **14 条审阅项 + 8 条 pending**。p047 的“后端到前端无延迟、瓶颈完全在拉取段”与 P1-04 的实证不一致，执行时将其作为待验证假设，而非已经确定的性能事实。p048 中“高概率/必现”的频率同样需要真实链路记录，修复不依赖复现频率成立。

### 1.3 批次完成标准

1. 每个来源都有独立验收证据或明确“验证未复现、无需对应生产改动”的记录；后者尤其适用于 P2-10，不能用 jsdom 替身证明系统复制成功。
2. 每个实施 commit 可构建、目标测试通过，测试覆盖生产入口；可测问题先增加失败覆盖再修改实现，红绿过程记入证据，commit 内同时交付实现与测试。
3. 现有测试语义失效时保留原测试或整体替换并说明理由；不将旧预期简单改成当前输出来消除红测。
4. 最终在集成分支执行完整后端、前端、轻量及真实全栈 E2E、桌面基础测试；跳过与环境干扰独立记录。
5. P1-06、P2-05 在最终状态表仍为“用户排除”。不通过放宽 lint、吞错误、关闭 SSRF 或只调大心跳阈值获得通过。

## 2. Agent、worktree 与写入边界

### 2.1 四槽位分工

默认同时使用 **1 个集成 Agent I + 最多 3 个实施 Agent A/B/C**，与当前四槽位容量一致。A/B/C 是可轮换的角色，不是固定持有所有工作包的永久进程。

|角色|职责|写入边界|
|---|---|---|
|I：集成负责人|冻结基线、创建 worktree、管理依赖、复核分支、按序集成、运行组合门禁、形成最终记录|仅集成 worktree；获合入主干授权后才操作主仓 main|
|A/B/C：实施负责人|独占一个工作包，完成代码、测试、分支内 commit 与交付记录|仅分配的 worktree；不写其他分支、不替其他 Agent 提交|
|独立 reviewer|由空闲的非作者 Agent 担任，检查最终分支 diff 和证据|只读被审分支；审阅意见由作者修复，不直接在作者 worktree 改代码|

实施者停止写入并提交后才进入独立 review；作者不能自己签收。槽位已满时让另一实施者完成当前 commit 后切换 review，不额外启动超配 Agent。

集成 Agent 不把未经复核的子结论直接拼接。安全、并发、迁移、协议变更检查代码与测试两方面；UI 变更同时检查真实浏览器和可访问性。

### 2.2 目录与分支

所有未来 worktree 位于 `/Users/karson/kar/code/` 内，保持用户写入范围。主仓 `/Users/karson/kar/code/kkmail` 保留为 main 控制入口，其他会话已有修改不搬移、不 stash、不提交。

|工作区|分支|用途|
|---|---|---|
|`/Users/karson/kar/code/kkmail_review_integration`|`review_fix/integration`|I 的组合验证分支，最后才进入 main|
|`/Users/karson/kar/code/kkmail_review_f01_logging`|`review_fix/f01_logging`|日志安全|
|`/Users/karson/kar/code/kkmail_review_f02_restore`|`review_fix/f02_restore`|恢复边界|
|`/Users/karson/kar/code/kkmail_review_f03_jobs`|`review_fix/f03_jobs`|任务原子唤醒与续跑|
|`/Users/karson/kar/code/kkmail_review_f04_sidebar`|`review_fix/f04_sidebar`|侧栏交互与几何|
|`/Users/karson/kar/code/kkmail_review_f05_mail_state`|`review_fix/f05_mail_state`|统计、位置和废纸篓|
|`/Users/karson/kar/code/kkmail_review_f06_health`|`review_fix/f06_health`|Worker 健康与同步指标|
|`/Users/karson/kar/code/kkmail_review_f07_realtime`|`review_fix/f07_realtime`|Outbox 发布顺序与 SSE|
|`/Users/karson/kar/code/kkmail_review_f08_reader`|`review_fix/f08_reader`|按需正文幂等与阅读器恢复|
|`/Users/karson/kar/code/kkmail_review_f09_settings`|`review_fix/f09_settings`|设置布局、OAuth 返回、modal 复制|
|`/Users/karson/kar/code/kkmail_review_f10_sync`|`review_fix/f10_sync`|增量/全量、前台触发与调度|
|`/Users/karson/kar/code/kkmail_review_f11_overlay`|`review_fix/f11_overlay`|生产浮层与快捷键偏好|

F00、F12 由 I 在 integration 执行，不额外创建开发分支。每包完成后保留其分支和 worktree 到集成检查结束；同一物理 worktree 不同时 checkout 两条分支，不把一套 node_modules 通过可写软链共享给多个实施者。

### 2.3 开始执行前的基线

I 在实际执行开始时记录 `main` 完整 SHA 为 B0。该 SHA 不必仍为本文核对基准；若源实现已变化，先重核所有条目并更新执行记录，不照旧行号覆盖新实现。保留现有 review 报告的历史性质。

未来创建命令的基本形态如下；先确认当前主仓分支为 main、路径/分支未被占用，再捕获并记录真实 B0：

```bash
review_base_sha="$(git rev-parse main)"
git worktree add -b review_fix/integration /Users/karson/kar/code/kkmail_review_integration "$review_base_sha"
```

F01 等分支从**所属波次已验证的 integration SHA** 创建，不统一从旧 B0 创建，不从别人的未审阅开发分支偷取依赖。已有目标路径或分支时先查询实际状态，不盲目重试创建或删除。

## 3. 并发波次、依赖和固定合入顺序

### 3.1 波次安排

每行开始前必须满足“进入条件”。一包失败时可继续完成同波独立包，但下个屏障不放行失败包的依赖。

|波次|进入条件|Agent A|Agent B|Agent C|I 的合入顺序与屏障|
|---|---|---|---|---|---|
|0|记录 B0、保护主仓现有改动|只读核对安全入口|只读核对调度入口|只读核对 UI/pending|I 完成 F00，产生验证后的 S0|
|1|S0|F01 日志安全|F04 侧栏|F06 Worker 健康|按 F01 → F04 → F06 合入，检查后记录 S1|
|2|S1|F02 备份恢复|F03 任务队列|F07 Outbox/SSE|按 F02 → F03 → F07 合入，检查后记录 S2|
|3|S2|F05 邮件状态/废纸篓|F08 正文竞态|F09 设置/复制|按 F05 → F08 → F09 合入；统一处理 API/codegen 交叉，记录 S3|
|4|S3|F10 场景化同步|只读交叉 review F07/F10 并发与协议|只读复核多账号压力、编写验收场景|F10 全部 commit 通过后整体合入，记录 S4|
|5|S4|只读 review F11|F11 生产浮层与快捷键|复核设置页/同步组合行为|F11 合入后记录 S5|
|6|S5|分担只读安全回归 review|分担只读协议/数据库 review|分担只读 UI/Electron review|I 执行 F12 组合验收、最终文档、准备主干合入|

F10 与 F11 **不并行改代码**：二者都修改设置页，可能修改 App、store 和 UI registry。波次 4/5 的空闲槽位用于 review/验证，不为了填满槽位强行拆开同一文件。

同波第一包通过后即可开始该包合入，不必等待另外两包完成；但下一波统一从合并完整、验证后的屏障 SHA 起步。这样避免每个后继随意挑选不同依赖集合。

### 3.2 主要依赖

- F03 → F05/F08/F10：任务完成/后继协议稳定后，其他链路再依赖去重与唤醒。
- F01 → F02/F07/F10：新增异常处理统一使用安全日志入口，不复制泄漏模式。
- F06 → F10：先分离进程心跳，再引入并发 Worker 执行；否则长任务验收会混入假 unhealthy。
- F05/F07/F08 → F10：统计、事件可靠性、正文幂等先闭环，避免把它们造成的延迟误归因于 polling。
- F04 → F09 → F10 → F11：控制 Sidebar/CSS、设置布局、同步设置按钮、快捷键设置之间的文件重叠。
- 全部实现 → F12：最后重新生成/核对契约、运行组合验收，不能拿各分支单独 PASS 代替组合 PASS。

### 3.3 文件冲突表

|共享区域|可能涉及的包|处理方式|
|---|---|---|
|`sync/delta.py` 的 provider 错误、任务后继及统计|F01、F03、F05、F10|分别安排波次 1、2、3、4，避免日志修复与队列修复同波改同一生产文件|
|`sync/jobs.py`、`worker/handlers.py`、delta 调度|F03、F05、F08、F10|按波次串行；F10 基于已合入 F03，禁止重写回旧标记语义|
|`worker/main.py`|F06、F10|F06 先行；F10 继承独立心跳和退出清理|
|`Sidebar.tsx`、`Sidebar.test.tsx`、`index.css`|F04、F09、F10、F11|生产样式与导航变更串行；新测试按场景单独文件减少同文件冲突|
|`App.tsx`、`SettingsModal.tsx`、`mailStore.ts`、UI registry|F09、F10、F11|后两个包不得从旧基线开发；F11 最后整合入口及偏好|
|`api/mail.py`、`mailCore.ts`、`schemaTypes.ts`|F08、F10；部分涉及 F07|F07 → F08 → F10 分属不同波次；F08 先完成幂等 DTO，F10 基于该版本扩展同步 API|
|`mail/storage/models.py`、Alembic migration|F07、F10|F07 唯一负责第一轮迁移；F10 仅在 F07 合入后读取最新 head 再分配下一 revision|
|OpenAPI JSON、生成 TS|F00、F07、F08、F10、F12|各包提交能匹配自身 API 的生成文件；integration 合并时由 I 从合并源码完整重生成，禁止手工拼接生成块|
|`docs/blueprint/` 与现行指南|多包|I 在 F12 统一写当前最终真相；各包先在独立交付记录写明确契约差异，互不编辑同一 blueprint|
|本 review 目录的执行记录|所有包|一包一份记录，由作者写本包文件；I 独占总状态和集成记录|

## 4. Commit 规划与交付规则

### 4.1 通用约束

- 同一工作包允许多个 commit；表中的每条 commit 都同时包含该步必需生产代码、有效测试及必要契约产物。新测试先红后绿，但不把红测单独提交成不可验证基线。
- 每个 commit 只解决表中定义的交付结果；不提交 `.scratch`、运行凭据、node_modules、dist、覆盖率和原始长日志。
- 分支最终通过独立 review 后冻结 head；后续任何实现修改必须新增修复 commit 并重跑相关检查，不 amend 已被其他分支依赖的 commit。
- 一个分支整体合入 integration，保留其内部 commit，不 squash，也不把多个包混成一个“大修复”commit。
- 已合入 integration 的 commit 不 rebase、不 force push；未交付且无下游引用的个人分支可由唯一作者整理，但整理后原 review 失效，重新提交证据。
- 原 review 不是执行状态权威。未来在本目录新增 `execution_log.md` 与 `delivery_fxx.md` 记录实际 SHA、base、测试、review、剩余风险；不在历史报告正文直接改“原来没有问题”。

### 4.2 建议 commit 清单

|工作包|commit 次序与建议主题|交付边界|
|---|---|---|
|F00|C01 `fix(api): regenerate baseline frontend contract`；C02 `test: restore intended backend fixture contracts`|先修初始类型漂移；再整理已确认的失效替身/测试语义，环境故障另列|
|F01|C01 `fix(logging): prevent provider exception secret leakage`|安全摘要、异常链输出和 formatter 回归一起提交|
|F02|C01 `fix(backup): confine blob restoration to validated staging`；C02 `fix(backup): reject restoration onto the source database`|路径安全与源库身份各有独立测试；两步均保留真实恢复演练|
|F03|C01 `fix(jobs): make deduplicated wakeups atomic`；C02 `fix(jobs): preserve requested successor execution state`|先消除完成竞争，再明确 payload/priority/time 合并语义及 20 轮计数|
|F04|C01 `fix(sidebar): close scoped searches on outside focus`；C02 `fix(sidebar): align folder hierarchy and inbox order`；C03 `style(sidebar): soften the settings entry`|分别交付 p045、p051、p050；保留几何和键盘验收|
|F05|C01 `fix(sync): refresh all locations after shared flag changes`；C02 `fix(sync): invalidate folders after location removal`；C03 `fix(imap): resolve the actual trash destination`|对应 P2-02、P2-03、P2-04，避免一次 commit 混三种状态语义|
|F06|C01 `fix(worker): renew process health independently of jobs`；C02 `fix(metrics): use the completed sync status`|心跳生命周期与指标筛选分开|
|F07|C01 `feat(realtime): persist committed outbox publication order`；C02 `fix(realtime): replay and deliver by publication cursor`|C01 增量迁移及未切换的发布基础；C02 完成协议切换、迁移收尾、前后端与所有回归|
|F08|C01 `fix(mail): make on-demand body synchronization idempotent`|后端状态结果、前端自动重取、选中消息隔离及 codegen 一并提交|
|F09|C01 `fix(settings): integrate sidebar controls into navigation`；C02 `fix(auth): initialize oauth return state without effect updates`；C03 `fix(clipboard): support copying inside native dialogs`|p049、P2-09、P2-10 分开；若 C03 真实验证不支持失败结论，改交付验证结论与必要焦点回归，不伪造生产修复|
|F10|C01 `feat(sync): separate delta and full synchronization requests`；C02 `fix(archive): isolate archive claims from metadata leases`；C03 `fix(sync): bound and prioritize provider work`；C04 `feat(frontend): expose scoped delta sync and authoritative progress`|API/请求状态；归档所有权；调度及连接限流；前端入口/旋转/场景触发，四步均可独立运行目标测试|
|F11|C01 `fix(ui): enable reference overlays in production`；C02 `feat(settings): persist configurable reference shortcuts`|生产可用与用户偏好分开，保留默认组合和复制边界|
|F12|C01 `docs: record integrated repair behavior and verification`|更新最终规范与逐项关闭证据，不偷塞未经 review 的生产修复|

清单是边界，不是必须凑齐的 commit 数。预计约 29 个实施/基线/文档 commit（包括纳入审阅资料的文档 commit，不含 integration/main merge commit）；实际应以可独立验证的工程结果为准。若一个步骤必须跨前后端才能正确工作，宁可在该 commit 一起交付，不制造半接口、坏类型或未接入的假绿测。额外修复需独立命名并说明触发失败，禁止把它隐藏在 merge commit。

## 5. 各工作包详细实施计划

### F00 基线恢复与测试分类

**负责**：I；开始于 B0，结束产生 S0。当前仅 review 目录未跟踪；正式执行前先将用户指定的审阅资料纳入单独文档 commit，不能混入后续生产修复。

1. 复核原始 7 项后端失败是否仍存在，按 [验证证据](review_evidence.md) 分类，而非一律当成生产缺陷。
2. C01 从当前后端导出 OpenAPI 并生成前端类型，提交 JSON/TS 的真实差异；此步只关闭初始 P2-08 漂移，不修 P2-05 鉴权。
3. C02 为新增会话撤销 LISTEN 通道、subscriber-only fanout、合法 COPYUID 返回形状和安全摘要语义建立生产入口覆盖。语义失效的旧用例整体替换并记录原因，保留旧行为中仍正确的断言。
4. 本机 IMAP fixture 只在隔离测试中显式启用允许私网；保留生产 SSRF 拒绝测试。不得修改全局默认来让 live 用例通过。
5. `rm` 包装器干扰不绕过、不修改本机配置；在标准 Linux 测试环境重放脚本用例，保留本机环境诊断。若标准环境仍失败，再定位真实脚本问题。
6. `test_a27_sync_folder_delta_sanitizes_errors` 的载荷丢失是 F03 范围，暂记已知红测，不在 F00 改预期。P2-09 lint 红测归 F09。基线清单明确这两条待关闭，最终门禁不允许沿用红测豁免。

**验收**：OpenAPI 两端检查通过；失效测试均有替代语义和原因记录；剩余失败可逐一映射到工作包或标准环境证据，不能仅保留一个“本来就红”的总备注。

### F01 日志安全：P1-05

**改动入口**：[redact.py](../../../src/mail_core/security/redact.py)、[logging_config.py](../../../src/mail_core/logging_config.py)、delta/reconcile/remote_push 的异常路径及相关测试。

1. 先构造真实 formatter 与 `log.exception` 回归，覆盖通用 `token`、JSON 引号值、URL 参数、Bearer、cause/context 异常链和 provider body 标记；不得用真实令牌。
2. provider I/O 错误使用受控摘要，不把带响应体的原始异常附进 INFO/ERROR/DEBUG 日志。修复范围覆盖同类调用点，不能只把一处 `log.exception` 换成 `log.error` 而让上层 traceback 再泄漏。
3. 补齐通用 token 字段脱敏作为兜底；生产 formatter 对异常链的输出策略与正文一致。保留异常类型、受控状态码、trace_id 和诊断所需调用位置，不保留原始响应文本。
4. 校验 `worker_jobs.last_error`、同步错误及 API 错误出口不把新安全摘要再扩展回原文。

**验收**：完整渲染日志及持久化错误中无输入秘密标记；仍可根据类型、状态、trace 关联任务。只检查 mock logger 参数不算通过。

### F02 恢复安全：P1-01、P1-02

**改动入口**：[backup/package.py](../../../src/mail_core/backup/package.py)、真实备份恢复演练和恶意成员测试；不修改加密格式来掩盖路径问题。

**C01 路径与解包**：

1. 在接触目标目录前完整校验 tar 成员名和类型：以 POSIX tar 路径解释，拒绝绝对路径、重复分隔造成的非规范路径、`..`、反斜杠/盘符绕过、软硬链接、设备文件和重名覆盖；正常 `blobs/` 目录与普通文件需有明确允许规则。
2. 不对路径做“静默修正后继续”，也不 `continue` 跳过恶意条目。整包在外部目标写入前失败，并给出不含敏感路径内容的受控错误。
3. 在可信父目录创建私有、不可预测 staging；只向该空树解包，逐级拒绝链接，写入使用独占临时文件、fsync 与原子替换。目标原始路径在 resolve 前检查末端链接，解析边界在最终写入前再次验证。
4. 默认恢复到新建、空目标目录；已有非空目录拒绝覆盖，既有恢复调用点和指南同步说明这一前提。合法历史包中的目录/文件布局先用真实生成包核对，不凭推测只允许某种 digest 文件名而误拒临时格式。
5. 文件路径检查与目标库身份预检全部通过后，才进入恢复；失败清理由本次 staging 所有权限制，不删除用户既有目录。

**C02 源库身份与恢复事务**：

1. URL 静态归一化移除用户名作为数据库身份维度，继续拒绝身份改写 query、多 host 和不完整 URL。
2. 只读连接源、目标，验证实际 PostgreSQL cluster `system_identifier` 与 database OID/名称。通过同一地址的不同角色、DNS/loopback/代理别名不能绕过；权限不足、源不可达或身份无法证明时拒绝进入破坏阶段，不回退为“字符串不同即可”。
3. `pg_control_system()` 等身份查询的实际权限在目标 PG16 环境验证；仅允许提供必要只读执行权限，不要求扩大为 superuser。克隆实例可能保留相同 system identifier，默认保守拒绝身份不明目标，不能为了演练成功减弱判定。
4. 默认要求新建空目标数据库，移除常规恢复对 `--clean` 的依赖；真实演练当前即创建新库。校验目标不含业务对象后，以 `pg_restore --exit-on-error --single-transaction --no-owner --no-privileges` 恢复，确认参数与实际二进制版本匹配。
5. 身份预检和进程启动之间仍存在目标被运维切换的竞态；执行时目标必须由操作者独占，恢复过程持有该目标的可证明所有权，禁止边运行边改连接目标。此约束写进指南和测试，不声称只读查询能抵御恶意 DBA 同时换库。
6. DB 还原成功后发布 staging Blob 目录。DB/文件系统无法组成同一事务：若最终目录发布失败，只保留隔离目标和诊断，不自动切换业务流量；清理/重试仅针对本次新目标，源库和源 Blob 保持不动。

**验收**：根外哨兵内容/权限不变；恶意成员在任何目标业务写入前拒绝；同源不同角色/别名拒绝且 pg_restore 未调用；真实包恢复到独立新库后，账号、正文、附件及解密内容一致。全过程只用独占测试库，不执行生产恢复。

### F03 任务队列原子协议：P1-03、P2-01

**改动入口**：[sync/jobs.py](../../../src/mail_core/sync/jobs.py)、[worker/handlers.py](../../../src/mail_core/worker/handlers.py)、delta/metadata/remote push 的续跑调用、并发与重试测试。

1. 先建立真实两 Session/多进程交错回归，不用概率 sleep：完成先于入队、入队先于完成、唯一约束竞争、任务失败/重领、重复唤醒都覆盖。
2. dedupe 活跃行读取使用行锁并刷新 ORM 旧对象；完成方也锁定、重读 payload/owner/status 后判定后继，不能只在原 SELECT 后加锁却继续用内存旧 payload。
3. 若锁等待后发现原行已 DONE/FAILED，不返回终态行冒充入队成功；重新查找可执行行或插入新任务。唯一约束 savepoint 失败后的回退执行同样的状态检查。
4. 将“运行中当前输入”与“请求中的下一次执行输入”分开。CLAIMED 行中保存一个明确的后继描述，至少包含业务 payload、priority、run_after；完成原行与创建后继在同一事务，原行清除后继标记。
5. PENDING 去重更新目标请求；不可用不分字段的浅合并覆盖业务语义。对当前生产 job 类型逐一列出合并规则：folder/message 身份必须相同；周期 `poll_round` 与本次逻辑续跑一致；新同步请求的关联 ID 合并保留；远端操作 retry 不丢服务商 next_attempt_at。
6. 时间/优先级区分业务：主动唤醒可以提前普通轮询，不能绕过 provider 限流最早允许时间；降低 priority 数字不能把后台任务永久提升为交互任务。多个请求合并以“最早合法执行时间”和明确 urgency 规则决定，不能简单统一取 min 或 max。
7. delta 每轮成功后传递新的 poll_round 和 priority；真实执行 20 轮，确认 reconcile 产生且计数复位。后继请求到达完成边界的任何时序，都有一个可执行承载者。
8. 旧 `_followup_*` 临时语义在本批一次性切换，不维护两套长期协议。执行前停止旧 Worker，扫描仍 active 的旧 payload 并在受控迁移步骤转换；不能让新旧 Worker 混跑。

**验收**：不存在带未消费唤醒的孤立 DONE 行；所有业务请求最终映射到当前或后继可执行任务；去重不造成无限循环/紧密重试。错误 detail 原用例按新后继语义验证真实载荷，不能改成接受 None。

### F04 侧栏：p045、p050、p051

**改动入口**：[Sidebar.tsx](../../../src/frontend/src/components/Sidebar.tsx)、[index.css](../../../src/frontend/src/index.css)、侧栏组件与真实几何 E2E。此包不改设置页布局。

**p045**：

1. 主列表搜索和各组独立使用容器 ref；范围包含输入、清空按钮与对应触发按钮。
2. pointerdown 的 composedPath 位于范围外时关闭；键盘 focusout 仅在 relatedTarget 离开范围后关闭。清空/输入框内部切换不得先触发关闭导致按钮失效，点击另一个搜索入口只影响对应区域。
3. 关闭复用现有清空词、恢复展开状态语义，保留 Esc、再次点击触发按钮和清空机制；IME 输入、滚动条和弹层相关目标均纳入测试。
4. 监听器随打开/关闭与卸载清理，不把瞬时搜索词持久化，不修改服务器分组/账号顺序。

**p051**：

1. 保持真实目录身份和树结构，不把某个子目录从父目录中拆出。账号直属展示顺序为收件箱入口 → 未读入口 → 其余真实目录；多个 inbox 同 role 保留独立可访问，顺序稳定。
2. 根据账号 disclosure 槽、图标与 24px 层级基准重算缩进，移除跨层硬编码 48px 的叠加。加载/错误/空状态和分类展开账号使用相同几何规则。
3. 组件测试验证顺序和语义层级；真实浏览器验证图标起点、父子阶梯和窄侧栏，不能仅检查 inline padding 数字。

**p050**：常态按钮透明/弱化边框，hover、active、focus-visible 仍可区分，全部引用已有语义颜色。保留设置入口稳定编号和可聚焦性。

**验收**：180px 侧栏和移动抽屉可用；全局/分组/账号搜索互不污染；旧拖放、账户复制、未知统计、Noselect 树和键盘导航不退化。p051 与既有顶层几何断言冲突时按当前有效几何契约补充覆盖，不放宽到肉眼大致对齐。

### F05 邮件状态与位置：P2-02、P2-03、P2-04

**改动入口**：delta、metadata、查询位置与 folder stats、[mutations.py](../../../src/mail_core/mail/application/mutations.py)、IMAP 写回。

1. 区分三种变化：共享 Message 状态、单个 MessageLocation 增删、整个 Message 删除；不要用一个 deleted 计数兼任三种含义。
2. 读状态变化时按页批量取得该邮件在同账号全部位置，形成受影响 folder ID 集；先 flush 再聚合，目录按稳定 ID 顺序取锁/重算，减少并发死锁。
3. metadata upsert 与 delta flag 共用已明确的受影响目录计算，不只修一条入口；未知读状态继续传播 null，本地未收敛意图保护保留。
4. 移除位置即将原目录加入 dirty 集，即使邮件仍在其他位置；只有孤儿才删除整个 Message。为仍保留消息的位置变更发送能使列表与详情位置失效的事件，不能假装整个消息被删除。
5. IMAP trash 在删除本地行前解析当前账号 role=trash 的真实 remote_id。唯一可选目标使用该值；不存在或歧义时返回明确可操作错误并保持本地数据，禁止默认猜测 Trash 或不安全 EXPUNGE。
6. provider 适配保持区别：Gmail 原生 trash API、Graph 既有软删除语义不强行套 IMAP 目录名。已持久化的旧 pending trash 操作在发送前重新解析目标，避免只修新操作。

**验收**：多位置先读后同步统计为 [0,0]；删一个标签原目录立即归零、其他目录保留；页级事件/统计去重；IMAP 非英文/含空格目标协议命令正确，失败不产生不相关邮件删除。

### F06 Worker 心跳和指标：P2-06、P2-07

1. 将进程健康续期从主 `_tick` 循环移到独立生命周期线程，使用独立 Session、有限超时和安全日志；与 job locked_at 心跳是两类记录，保留各自职责。
2. run 启动后、处理任务前发首个心跳；停止时设置 event、有限 join，防止 Worker 线程已经退出后还持续发送健康记录。嵌入式 Worker 重启/重复 run 不得遗留多个心跳线程。
3. 记录进程存活和必要的 active_jobs；不声称线程存活能证明任务进展。DB 不可达时不伪造健康，主线程死锁与服务存活的进一步判定保留清晰语义。
4. 同步指标使用 `SyncRunStatus.DONE`，真实数据库验证有/无成功记录；本次不悄悄改动 `max_sync_lag_seconds` 的聚合口径。

**验收**：正常慢任务超过 60 秒仍健康；故障/停止后按阈值变旧；SIGTERM 清理无孤儿心跳。正式验收包含一次真实跨阈值进程测试，快速测试可以缩短测试阈值，但不能只有 fake clock。

### F07 提交后的 Outbox 发布顺序：P1-04

**设计取向**：推荐新增**提交后持久发布序号**，保留 Outbox 业务主键作为存储身份，SSE 游标改用发布顺序。不通过延迟几秒、重复抓最近 N 个 ID 或去掉客户端去重来掩盖提交乱序；不在所有业务写事务上持有全局网络期锁。

1. C01 添加 nullable `publication_seq`、发布时刻及唯一索引，增加单例发布状态行，保存下个序号和流 epoch。此步为增量迁移，现有运行路径仍可工作；迁移 revision 由本包执行时读取当前唯一 head 分配，禁止并行预占编号。
2. 发布者只扫描已经提交且尚未发布的 Outbox 行，在短事务锁定单例状态行，分配一批连续序号，持久化行与计数器后提交。分配状态是事务性值，回滚不能把未发布序号当已发布；状态行锁覆盖提交顺序，发布事务不做网络 I/O。
3. 多进程 API 可竞争发布锁，但每个 API 用自身进度读取已发布事件、按 publication_seq 向本地订阅者广播。全局 `dispatched_at` 不再作为某个进程可以替其他进程消费事件的凭据。
4. 新订阅依旧先注册再回放；回放和在线使用同一 epoch/seq 语义。丢 NOTIFY、进程重启或短暂无订阅者后，API 通过可恢复持久扫描续跑，而不是只依赖一次通知。
5. SSE ID 采用版本化 epoch/seq 字符串；旧整数 Last-Event-ID/after 只触发一次 resync hint 并进入新协议，不继续维护旧 ID 重放实现。参数类型、OpenAPI、前端 parser 及 resync 缓存失效同步更新。
6. resync hint 需要刷新列表、统计、账号/分组组织及必要详情；不仅清除 inbox。队列溢出、保留窗口过期、未知 epoch 都显式走此收敛路径。
7. C02 完成运行协议切换和第二个线性迁移，清理不再使用的全局消费状态；历史保留窗口内事件按发布规则背填，设置新 epoch。部署切换要求停止旧 API/Worker、结束未决事务、验证迁移，再统一启新版本，不混跑两套游标协议。
8. 保留最近事件的清理按已提交发布时刻/序号进行。迁移前验证可恢复备份；降级前明确发布 epoch 与客户端游标重置，禁止自动删除业务邮件。

**验证门槛**：两个真实事务强制乱序提交；两个 API 进程各有订阅者；重连、丢通知、发布事务 rollback、进程被杀、队列溢出、保留窗口修剪、账号过滤和全局事件。每个有效变更都可交付或触发有证据的全量收敛，接受幂等重复，不能静默漏事件。

**设计审查点**：F07 C02 前 reviewer 检查序号“何时可见”的证明及多 API 交付，实测吞吐/锁等待。如果推荐结构在现有约束下不能满足上述证明，先更新本计划对应章节并独立 review，不直接切成“增加重试窗口”的临时方案。

### F08 正文按需同步幂等：p048

**改动入口**：[message_details.py](../../../src/mail_core/mail/application/message_details.py)、[api/mail.py](../../../src/mail_core/api/mail.py)、[MessageReader.tsx](../../../src/frontend/src/components/MessageReader.tsx)、API client/类型及回归。

1. 锁定归档状态并重读；返回明确状态结果，而不是在已经完成时抛 `MessageBodyAlreadyArchived`。建议结果为 `queued`、`in_progress`、`complete`，job_id 仅在确有任务时存在。
2. 已完成返回 HTTP 200/complete；新入队返回 HTTP 202/queued；已在处理返回 HTTP 202/in_progress。不存在、不可寻址、归档状态缺失仍保留独立失败语义；不通过空 job_id 冒充入队。
3. 竞争时复用 F03 的原子任务协议；当前归档进行中不重复重置 state/retry_count，不清除另一个 Worker 的 claim。
4. 阅读器对三种成功结果均失效并重新获取当前详情，complete 不显示红色同步错误；队列/处理状态保持权威 state 驱动。接口只负责调度，不在 API 请求内拉 MIME。
5. 以请求发起时 message ID 与组件选中版本隔离 late response；从 A 切到 B 后，A 的完成/失败不能把 B 变成已排队或错误。无需整页刷新，不依赖匹配英文错误字符串。
6. 后端 DTO、OpenAPI JSON、前端生成类型与 client 同 commit 更新；废弃旧的“完成即冲突”路径，避免长期双契约。

**验收**：真实 PG 两会话复现“GET 未归档 → Worker 完成 → POST”；POST 成功且无重复任务；阅读器自动显示新正文。再覆盖合法空正文、解析错误、配额暂停、真正网络失败和连续切换邮件。

### F09 设置布局、OAuth 返回与复制：p049、P2-09、P2-10

1. p049 删除 settings-page-head 整行及返回邮件按钮，将 sidebar toggle 放入 settings-nav。移动端横向设置分类、macOS 标题栏拖动区与 no-drag 按钮都要实测；设置仍可通过明确导航返回邮件，保留必要的 Esc/侧栏导航路径。
2. 现有 ST01 保留其侧栏按钮身份；移除的 ST02/ST03 在 registry 标记废弃，不把旧编号分配给新含义元素。新控件按现有稳定编号约定分配。
3. P2-09 在会话恢复/登录成功处理或可推导初始化路径消费 `#oauth-return`，打开设置、传递一次待消费状态并清理 hash。避免同步 setState effect；不为单条告警关闭全局规则。
4. P2-10 先在隔离浏览器 profile 中用真实用户点击、缺失 Clipboard API 和真实复制/粘贴验证原生 dialog 结果，保存/恢复剪贴板或使用隔离 clipboard。此前只证明焦点失败，不能把替身返回 false 当原生命令失败。
5. 如确认回退失败，将 textarea 放入活动 modal 内；外层页面则使用 body。保存原 activeElement、选区与输入选中范围，finally 清理并尽可能恢复；API 拒绝后的回退也需保留用户激活语义和明确失败反馈。
6. 如果真实复制已经成功，仅记录该结论并补必要焦点/选择覆盖；不因计划已列 commit 而强行改动正确路径。仍需修复确认的焦点副作用，具体取舍以证据为准。

**验收**：桌面/窄屏设置布局不占冗余顶栏；OAuth 回到设置且状态仅消费一次；lint 为绿；复制目标文本准确、焦点不跳出 dialog，邮件无脚本 iframe 和 Electron 权限边界不放宽。

### F10 场景化同步与时延：p046、p047

本包是最大交叉包，必须基于 S3 开始；不与其他 Agent 同时修改 worker、App、SettingsModal、MessageList 或共享 client。

#### A. 先度量，再冻结可测参数

1. 记录五段耗时：服务端可见邮件 → 开始 delta、provider RTT、元数据事务提交、Outbox 发布/SSE 到达、React Query 刷新完成。使用现有 trace/job/request 标识，不输出邮件正文、令牌和完整账号地址。
2. 重现“归档积压”“全部账号/千级账号”“窗口聚焦”“切账号”“手动点击”场景。新邮件感知不能只用 API enqueue 200/202 作为结束时间。
3. 计划推荐初始值：活跃轮询 **8 秒**，冷账号保留 **30 秒**基础轮询，自动触发冷却 **12 秒**，全局 mail-provider 连接上限 **8**，全部收件箱自动前台拉取最多 **3** 个最近活跃账号。均落在 pending 给定范围，除非测量证明不能满足；不是新增一整套用户配置面板。
4. “秒级”限定为 provider 正常响应、未被其限流的测量目标；尊重服务端 Retry-After 和已配置抓取超时。对单个已在进行的不可抢占网络请求，不承诺任意时刻立即终止；记录这一延迟上界，不把参数翻转声称成彻底无等待。

#### B. API、scope 与真实完成状态（C01）

1. 新增明确轻量 delta 请求入口，与现有 full sync 服务分开。复用现有 account/group/folder scope 解析及互斥校验；只为具有基线的可选目标入队 delta，不在日常手动刷新时偷偷运行全量结构扫描。
2. 未建立基线账号：返回明确 baseline 初始化状态，复用新账号首次 full sync；不静默跳过并宣称增量已完成。禁用账号和 Noselect 不进入自动调度。
3. 单账号/精确文件夹按当前选择；组视图解析当前成员；全局手动操作可覆盖启用账号，但分批入队、去重、并发受限。全局**自动 focus**只触发最近活跃 3 个账号，不能扩展成每次聚焦同步全部千个账号。
4. 引入可追踪同步请求及目标状态，至少记录 request ID、目标、queued/running/complete/failed 与受控失败摘要。目标关联真实 job/后继执行，F03 coalescing 时合并请求关联，不能把仍需后继的请求提前计为完成。
5. 旋转状态以服务端请求/目标收敛为准；HTTP 接收完成只表示已排队。刷新页面、重复点击和 SSE 重连后仍可查询最近未完成请求，不依赖本地 boolean 永远旋转或提前停止。
6. 迁移由本包在 F07 之后独占分配下一 revision；请求/活动表若需新增，模型、迁移、索引和清理一起交付。只保存调度所需短期状态，不长期保留逐次活动日志。
7. 保留 full sync 新账号初始化与设置单账号/全账号入口；名称与 tooltip 明确全量，列表不再调用该入口。手动 full 必须在合法扫描租约/fencing 下开启新 metadata 基线、清理需要重建的扫描游标，而非只重新入队后沿旧 cursor 继续增量；本地邮件和未收敛意图保留，仅完整扫描结束后才能 reconcile 删除远端已不存在的位置。限流/失败不把未完成全量扫描标为完成。

#### C. 调度、资源与冷热轮询（C02、C03）

C02 先交付归档 claim revision 与扫描租约解耦，保留现有执行器即可验证两个 Worker 的同账号并发及迟到写入拒绝。C03 再引入有限并发执行器、全局连接 permit、优先级及冷热调度；不能让并发执行先于所有权隔离上线。

|任务|建议优先级（小值优先）|说明|
|---|---|---|
|按需单封正文|10|保持用户主动读取优先；不将所有归档冒充按需|
|delta 新邮件发现|20|主动及定时 delta；合法限流时间仍有效|
|远端写回|40|保留既有本地意图收敛|
|首次目录发现/metadata 初始化|50|保证新账号最终可建立基线|
|例行正文/附件归档|80|替换所有批量入队点的 40/60；不得只改单处常量|
|周期 reconcile|90|低优对账；仍需防长期饥饿|

01. 扫描并统一所有入队点，含 metadata 完成、归档续批、quota 恢复、手动入口；优先级定义集中在现有领域落点，不新增彼此不同的常量副本。
02. 当前 `_tick` 先 claim 5 个再串行处理会形成不可抢占队列。改为按空闲执行槽认领，单进程最多 4 个独立作业并发；每作业独立 Session，不能共享 ORM Session。无空闲槽不预领更多任务，低优归档不把高优 delta 预先挤在本地队列后。
03. 并发作业必须区分 `claim_worker_id` 与唯一 `execution_owner`。任务完成用原 claim 身份；账号租约/归档 claim 使用含 job/attempt 的唯一执行身份，避免同一 Worker 内并发任务以“同 owner”重入租约、递增 fencing 并互相作废。
04. 同账号扫描与写回继续用现有账号租约；**归档网络下载不再长期持有扫描账号租约**，否则仅翻转 priority 仍不能满足 p047。归档改为按 MessageArchiveState 行独占认领，并添加单调 claim revision，在拉取前、拉取后与发布事务内校验执行 owner/revision、消息 remote_id 和归档状态；旧 Worker 的迟到写入拒绝。正文/Blob 发布只在短事务内完成锁与一致性校验，复用 digest 发布/GC 互斥，不在网络期间持业务事务。
05. 上述归档所有权切换需要本包下一条线性迁移，并同步替换原“archive 使用扫描账号 fencing”的测试契约。例行归档一次至多一封 MIME/其附件，与 metadata 可使用不同外部连接并行；真实测试覆盖同账号归档慢请求期间新 metadata 仍能推进、删除/远端 ID 变化、旧 claim 续写拒绝及 SIGKILL 重领。不能只把 batch_size 改为 1 就宣称同账号已解除阻塞。
06. 全局上限必须跨 API/多个 Worker 生效，不能只放一个 Python Semaphore。推荐复用 PostgreSQL session advisory lock 作为 8 个全局 mail-provider 连接 permit，使用专用、无业务事务连接持锁，释放与真实连接关闭在 finally 绑定；DB 控制连接异常时中止新外联并收敛已有调用。
07. 其中 2 个 permit 预留给交互/metadata，后台 archive 最多使用其余 6 个；metadata 可使用总池。拿不到 permit 时不持业务事务忙等，不计业务失败，按 F03 合法延迟重新入队。
08. permit 覆盖实际 HTTP 请求/IMAP session，不仅覆盖 provider 对象。Gmail ThreadPool 的每个 metadata HTTP 连接计入上限；token 刷新与 API 请求不能嵌套持同一个 permit 再申请造成死锁。IMAP 复用会话直到关闭才释放。
09. 活跃账号通过有期限的服务端活动记录续期，多客户端取有效并集后按最近活动选 top 3；页面隐藏/活动过期后恢复冷轮询。自动事件冷却只限制自动触发，手动按钮允许明确刷新，但仍受服务端去重、限流与实际请求在途约束。
10. 防止 archive/reconcile 饥饿：任务年龄与实际完成量纳入压力验收；若持续前台活动导致后台长期不前进，使用明确的每轮后台进度预算，而非把 archive 恢复为高于 delta 的固定优先级。

session permit 方案在实现前要验证 psycopg 连接生命周期、异常释放、DB 池额外容量及多进程行为。PG 连接断开和外部 socket 停止并非同一个原子事件，必须测试失联时的关闭/停止准入，不能在文档声称绝对无瞬时超额而无证据。

#### D. 前端入口与反馈（C04）

1. 列表按钮文案为“增量同步（检查新邮件）”，在真实请求 queued/running 时旋转，目标完成/失败后停止；失败保留错误反馈，清除成功 list-note 横条。不会因为普通 Query refetch 就显示远端同步成功。
2. 设置账户管理提供单账号和全部账号“全量同步（重新扫描全部文件夹与元数据）”；新账号加入仍自动 full，不把用户全量入口删掉。
3. 使用一个共享 scope/冷却入口处理 window focus、visibility 恢复、账号切换和手动按钮；自动事件 12 秒冷却，React StrictMode 重挂不重复提交，选择变化和卸载清理监听器。
4. 不把含凭据或账号活动集合写入永久浏览器存储；已有查询 scope、禁用账号规则、未知统计与请求错误处理保持一致。
5. SSE 事件与请求状态查询组合恢复旋转；连接断开时有限查询权威状态，不能无限请求或把掉线解释为成功。

**验收**：真实 PG+IMAP+Worker+SPA 下，从入箱到列表出现记录各段耗时；归档积压时 delta 能在可用执行/连接槽到来后先于下一批归档执行；全局实际连接峰值不超过设计上限，前台自动触发账号数不超过 3；provider 429 不紧密重试；全部同步与 scoped delta 不串范围；请求完成/失败后动画和提示一致。

### F11 生产序号浮层与快捷键：p052

1. C01 移除 App 对 `import.meta.env.DEV` 的生产禁用，仍 lazy load；登录/错误/设置等允许的应用壳按既有安全边界接入，邮件 sandbox 不获脚本或系统权限。
2. C02 本地持久化“功能启用”和快捷键描述，默认保留 macOS `Meta+Shift+Period`、其他平台 `Control+Shift+Period`；不将快捷键存为任意 JS 或依赖按键显示字符串执行。
3. 设置通用页提供录入、清空/恢复默认和即时反馈；录入中阻断旧快捷键误触发，拒绝仅修饰键、保留系统组合及不支持组合，明确冲突说明。配置无效回退默认，不清空用户其他偏好。
4. 统一一个匹配器使用 platform/modifier/code，忽略 repeat、IME composing；Escape 只关闭浮层并阻断级联，输入框快捷键行为按录入状态区分。
5. 生产 Vite 构建真实页面验证，不以单独 mount 浮层组件代替 App 集成验证；复制编号沿用 F09 helper，失败反馈继续可见。

**验收**：生产包默认组合可打开/关闭；自定义即时生效且刷新后保留；禁用/恢复默认正确；Windows/Linux/macOS 匹配器与至少可用平台的真实操作有证据，不宣称未实测平台已通过。

### F12 最终组合验证与文档

1. 从最终 integration tree 重导出 OpenAPI 和生成 TS，检查所有 API 分支的组合结果；若有真实漂移，在对应来源分支补修复或新增明确修复 commit，不手改生成文件。
2. 更新 blueprint 的任务后继、发布游标、调度优先级、同步场景、侧栏几何、生产浮层/快捷键约定；更新恢复指南和 API 文档。旧 review 保留，新增逐条解决证据与实际 SHA。
3. 对 22 个来源建立最终状态表：已修复、验证无需对应改动、待验证/阻塞；排除的两条另列。没有证据不写“全部完成”。
4. p045–p052 在真正完成组合验收后，才按项目 pending 工具归档；该元数据收尾不走 task 流程，也不提前手工改“已处理”。

## 6. 测试资源并发与门禁分层

### 6.1 资源所有权

|资源|并发规则|
|---|---|
|Python DB 测试|仅项目运行器，每次独占新库、run UUID、Blob 根和覆盖文件；可以并行，但 I 控制总 DB 负载，禁止复用另一个包的临时库|
|真实 IMAP fixture|默认全局互斥；F05/F08/F10/全栈测试排队使用；需要并行则每包独立容器、端口、maildir 和凭据，不能共享同一邮箱并互相清信|
|前端 Vitest/TS/build|各 worktree 独立依赖/产物目录，可并行；不在同一 worktree 同时 build、改源码和浏览器验收|
|E2E preview/API 端口|每包独立端口和 profile；不得误用别包已启动服务，端口被占先查所有者|
|Electron|隔离 userData 与数据目录；按桌面测试文档运行，禁止复用实际用户邮件配置|
|DB migration revision|F07 后 F10 串行分配；I 验证线性唯一 head 与恢复演练|
|本机 clipboard|用隔离环境，或测试前后保持原值；不读取/记录用户原剪贴板内容到证据|
|Git index/主仓 main|只有 I 操作；Agent 不能在主仓对全部改动 git add/commit|

### 6.2 每包门禁

每个作者交付：base SHA、commit 清单、`git diff --stat`、改动文件、关联来源、红绿证据、执行命令/结果、未实测范围。独立 reviewer 对同一最终 head 给出结论；作者修改后重新检查受影响部分。

后端涉及并发、迁移、真实协议的包必须有 PostgreSQL/协议证据；UI 的低影响样式不写镜像实现的测试，但 F04/F09/F11 的几何、焦点、生产加载必须在浏览器验证。具体新测试文件执行前按现有测试目录组织，不能在计划中宣称尚不存在的文件可直接运行。

### 6.3 最终验收矩阵

命令从实际 integration worktree 根执行；前置为依赖已安装、项目专用 PG/IMAP 服务已就绪且随机专用凭据由用户现有测试配置提供。失败停止对应合入步骤，先查已创建资源状态，不盲目重跑会改变外部状态的操作。

```bash
scripts/run-mail-core-tests.sh run
.venv/bin/python scripts/export_openapi.py --check
npm --prefix src/frontend test
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
npm --prefix src/frontend run test:e2e
.venv/bin/python scripts/run_full_stack_e2e.py
npm --prefix src/desktop test
.venv/bin/pytest .repo_template/tests -q -m contract
```

另对 F02 运行真实恢复演练，对 F06 运行跨健康阈值进程测试，对 F07/F10 运行多进程/受限并发专项，对 F09/F11 运行原生 modal 与生产构建场景。测试配置必须实际选中新增用例；不能仅执行旧的默认 18 项轻量场景就声称覆盖新功能。

真实 Electron OAuth 条件允许时显式开启既有模式重跑；没有条件则在最终记录标为未验证，而非静默 skip 后算全绿。本机 `rm` 干扰在标准环境复核；不得修改保护器、增加测试忽略或关闭生产 SSRF。

不把 P1-06 对应的干净桌面打包 job 作为本批已关闭门禁；基础桌面测试仍需通过。P2-05 端点行为保持排除前状态。

## 7. 合入、冲突、回退与最终主干操作

### 7.1 分支进入 integration

1. 作者完成全部目标 commit 和门禁，worktree 干净；I 验证最终 head 与 reviewer 所审 head 相同。
2. I 先检查 `merge-base` 与声明基线，确保没有未声明依赖和混入其他工作。发现混入即停止该包，不自行把别人的 commit 拆掉。
3. 在 integration 按波次顺序执行 `git merge --no-ff --no-commit review_fix/fxx_name`，检查合并结果，再运行对应组合门禁。这里仅描述未来操作，不表示当前允许执行。
4. 生成文件冲突由 I 在合并源码上重生成后暂存；简单路径冲突按已审阅的双方意图解。发现语义重叠或需要新增生产实现时，退出 pending merge，由作者基于最新屏障新增修复 commit 并重新 review，不在 merge commit 临时编程。
5. 通过后创建一个明确 `merge: integrate fxx ...` 的 merge commit，保留分支内部所有实施 commit；记录两侧 parent SHA、验证摘要和生成文件差异。
6. 失败则先保存诊断和文件状态；确认只有本次 merge 产生的变动后 `git merge --abort`。不得 reset --hard，不删除分支/worktree，不以强行接受 ours/theirs 消掉问题。

merge commit 只包含审阅过的合并结果、必要冲突解决和从该结果生成的契约产物。修复生产缺陷使用额外实施 commit，不能把“集成测试红了顺手修”混进 merge。

### 7.2 main 在期间前进

integration 分支构建期间不冻结用户其他工作。如果 main 出现新 commit，I 先审阅增量及文件重叠；无重叠也必须把最新 main 合入 integration 并重跑组合检查。存在同类功能已被其他会话修复时，停止重复实现，重新核对来源映射和计划，而不是覆盖新成果。

默认采用 merge 吸收 main，保留已审 commit SHA，不 rebase 已集成历史。若发现新 main 改动与本批决策冲突，形成明确冲突说明并待用户取舍；其他无关包仍可在自身边界完成。

### 7.3 最终主干合入

执行授权和 main 合入授权分别确认。未来用户若已明确批准整个批次按本计划合入，则按批准范围执行，无需对每次普通 merge 重复询问；**当前只授权写计划，不授权未来任何 merge**。

最终步骤：

1. 固定 S-final，完整门禁与最终 review 对应同一 head，22 个来源状态表和两条排除记录齐全。
2. I 确认 main worktree 无其他会话未提交改动，确认最新 main 已在 S-final 祖先中；否则回到 integration 同步/验证。
3. 获主干合入授权后，在 main 以 `--no-ff --no-commit` 合入 `review_fix/integration`，检查 tree 和相关只读/测试门禁后创建最终 merge commit。
4. 该步骤仅合入代码，不 push、不部署、不切换生产数据库。发布、迁移和生产恢复须另有明确授权及备份/回退验证。
5. 保留分支及 worktree，直到最终 merge 及证据核验完成。清理时只删除明确属于本批且已经干净/已合入的 worktree，使用 Git 标准移除，不批量删除用户目录。

### 7.4 回退

- 尚未进 main：保留失败包，integration 可从上一屏障建立新的候选分支；不修改已审历史，不把错误结果继续给依赖包。
- 已进 main、尚未部署：用 `git revert -m 1 <本批最终merge的实际SHA>` 撤销整批，先核对后续依赖并执行测试；不 reset 或强推。
- 单包已被后续包依赖：不能随意单独 revert F03/F07/F10 的基础提交。先根据依赖图决定撤销整批或补前向修复。
- 数据库已经升级：代码 revert 不等于数据库回退；按 F07/F10 迁移演练结果执行。恢复备份、降级或清理数据不包含在普通 Git 回退授权中。

## 8. 执行记录与最终交付

未来真正执行时，在本目录追加以下文档；本次不预填不存在的 SHA/PASS：

- `execution_log.md`：B0、各屏障 SHA、分支/worktree 所有者、集成顺序、当前正在验证的 head、资源互斥占用。
- `delivery_f01.md` 至 `delivery_f11.md`：各包 commit、文件范围、红绿证据、独立 review、遗留风险；F00/F12 可直接记总日志。
- `repair_results.md`：22 个来源的最终状态、修复 SHA、实际验收证据、排除条目、环境差异、未实测平台及发布前必要条件。

验收记录使用 ISO 8601 带时区；错误只保留必要脱敏摘要，原始产物仍存各 worktree 的 `.scratch/`。不复制真实凭据、邮件正文、数据库 URL 或用户剪贴板内容进 review 目录。

本计划完成条件是：范围、写入边界、并发图、commit 切分、合入协议和验证要求足够明确，且文档通过格式/链接/覆盖检查。它不是实现完成或立项/发布批准记录。
