# Task review t061（reviewer_focus: 代码）

- task：`t061_idle_inbox_and_all_folder_status_patrol`
- spec：`docs/tasks/t061_idle_inbox_and_all_folder_status_patrol/spec.md`
- diff_anchor：`327acc0250f26c71d7ad2b777e876b92ff79c484`
- target：`git -C '/home/hatch/workspace/kkmail_t061' diff 327acc0250f26c71d7ad2b777e876b92ff79c484`
- round：1
- reviewed_at：2026-10-28T04:56:26+08:00

reviewed_scope: 914854af72442071

## Findings

### t061_code_f001 - 巡检探测失败不推进 last_probe_at：失败文件夹每 60 秒被重复登录探测，且失败集 ≥ 单轮上限时其余文件夹被永久饿死；max_unprobed_s 配置从未被调度逻辑消费

- 严重度：important
- 锚点：违反 AC-014（探测失败应「在后续周期自动重新探测」，周期默认 1200 秒）与 AC-013（「任一文件夹的连续未探测时长不超过可配置上限」）；失败场景见下。
- 位置：`src/mail_core/sync/patrol.py:160-178`（三条失败路径均在写 cursor 前 `continue`）、`src/mail_core/sync/patrol.py:43,51`（`max_unprobed_s` 仅定义与灌入配置）、`src/mail_core/worker/main.py` 调度循环（`schedule_interval_s` 默认 60 秒调用一次 `_schedule_periodic_sync_once`）
- 问题：`schedule_folder_status_patrol` 只在探测成功路径才写 `cursor["last_probe_at"]`（成功路径在失败分支之后）。失败（抛异常、`status is None`、provider 构建失败）的文件夹 `last_probe_at` 永不更新，于是：(1) 它在每个 60 秒调度 sweep 中都保持 due，被以一次全新 IMAP 登录 + STATUS 每分钟重试一次，远密于 AC-014 的「后续周期」（1200 秒）——对失败原因恰为限流/服务器异常的文件夹形成持续登录压力，代码注释（patrol.py:175 附近）自称 "retried next cycle" 与实际行为不符；(2) due 列表按 `(last_epoch, folder_id)` 升序排序后截取 `max_probes`（默认 200，patrol.py:135-136），持续失败的文件夹 epoch 恒为 0.0 或最旧值，永远排在最前——当持续失败文件夹数 ≥200 时，每轮选中的恒为同一失败集，其余全部文件夹永远得不到探测，AC-013 的未探测时长上限保证被击穿；(3) 本应兜底该上限的 `folder_patrol_max_unprobed_s`（默认 2400）在整个 `src/` 中除配置定义/校验/灌入 `PatrolConfig` 外无任何消费点（grep 实证），是死配置，无法把超限文件夹强制提前。
- 建议：失败路径也记录探测尝试时刻（例如单独的 `last_probe_attempt_at`，或失败时同样推进 `last_probe_at` 并另记失败计数），使失败文件夹按巡检周期（或带退避）才重新 due；同时在选择逻辑中消费 `max_unprobed_s`：已超过上限的文件夹强制优先入选，保证轮转上界可兑现。

### t061_code_f002 - 巡检每轮对全部文件夹逐个 session.get 检查点，N+1 查询随文件夹总量线性放大

- 严重度：minor
- 锚点：行为缺陷（性能）+ 失败场景：spec 按现状约 100、规划近千账号设计，每账号数个至数十文件夹即数千至数万文件夹；巡检 sweep 每 60 秒运行一次。
- 位置：`src/mail_core/sync/patrol.py:104-121`
- 问题：函数先一条查询载入全部非收件箱文件夹，随后在 Python 循环内对每个文件夹逐个 `session.get(SyncCheckpoint, ...)` 取检查点——含本轮根本未到期的文件夹。文件夹总量 N 时每 sweep 至少 N 次主键往返查询，每分钟重复。本 task 同一交付内的 `idle_watcher._load_candidates` 已示范了一条 join 查询取齐 Account/Folder/SyncCheckpoint 的写法，巡检未采用。
- 建议：把 SyncCheckpoint 改为与 Folder/Account 同一 join 查询（或按本轮候选 folder_id 集合批量 `IN` 查询）一次取齐，消除逐行往返。

## 结论

- 本轮新发现：2 条（important 1、minor 1、critical 0）
- 未进表的提示：
  - 文件过大（按降级规则仅提示）：新建 `src/mail_core/sync/idle_watcher.py` 467 行，超实现源码 400 行 minor 阈值；`src/mail_core/providers/imap.py` 现 1617 行（本 task 净增约 212 行），早已超 800 行 important 阈值，本 task 继续在其中堆 IDLE 会话实现。未见由此直接导致的可观测缺陷，未进 finding 表。
  - 圈复杂度（结论段提示）：`schedule_folder_status_patrol`（patrol.py）手算近似 CC 约 15-17（多重失败分支 + 嵌套循环），`IdleWatcherManager._watch_loop` 约 11；本机无 radon/lizard 工具，未能工具实测。未见由此直接导致的分支漏处理，未单独进表（f001 的缺陷已按行为本身锚定）。
  - 低置信观察（未进表）：`idle_watcher.py:432-434` 的凭据指纹由 `credential_ref + account.updated_at + folder.id` 组成；经核 `accounts/service.py` 的 `update_account` 在凭据变更时会赋值 `acc.credential_ref` 并 flush，预计会触发 `Account.updated_at` 的 onupdate 而使指纹变化、AC-006 成立；但若存在只写 `credential_secrets` 行而不触碰 Account 行的凭据轮换路径，指纹将不变、watcher 不会重连且 PermanentAuthError 的 blocked 状态不会解除。建议 implementer 在处置时顺手核实一遍该路径是否存在。
  - `git status` 中存在未跟踪的 `src/desktop/node_modules/`，与本 task 交付无关，未纳入审查范围。
- 总体判断：巡检失败路径的重试节奏与轮转上界各有一处可复现的契约违反（f001，important），故 FAIL；IDLE 侧（能力门控、两池分离、唤醒入队、退避打散、状态跟随）与 STATUS 变化判定经代码查证与 fake IMAP 服务器测试复跑均成立，未发现 blocking 问题。
- 系统性 follow-up：无（f001/f002 均为本 task 内修复，不另立项）

## AC 复验方式

- AC-001：re_verified — 复跑 fake IMAP 服务器测试（`test_idle_not_supported_without_capability`、IDLE 会话系列全过）；查证 `idle_watcher._load_candidates` 的候选过滤（sync_enabled / provider=imap / role=inbox / 非 paused / full_scan_complete）与 `imap.py:open_idle_session` 的 CAPABILITY 门控 + 只 SELECT 目标收件箱。
- AC-002：trust_prior — provider 层推送信号已由我复跑证实（fake 服务器 `* 3 EXISTS` → `wait_for_change` 返回 `"changed"`，亚秒级）；但「入队并执行、新邮件落库」的 DB 全链路断言在 `test_ac001_ac002_wake_enqueues_delta`，该测试在 unit 模式下 skip（无 DB），依赖实施侧证据，我未能独立复跑。
- AC-003：re_verified — 复跑纯逻辑退避测试（指数增长、上限封顶、抖动区间）与 fake 服务器断线检测测试（`test_idle_session_drop_detected`）；抖动为每 watch 线程独立 `random.random()`，多账号同时断线时重连时刻被打散的代码路径已查证。
- AC-004：re_verified — 全量阅读新模块：`idle_watcher.py` 只写 `AppSetting` 状态与 `enqueue_job`，`patrol.py` 只写 `SyncCheckpoint.cursor` 与 `enqueue_job`，两文件无任何 messages/message_bodies 写入（grep 实证）；入队去重键与既有 `delta:{account}:{folder}` 一致。
- AC-005：re_verified — 复跑 holder 选择纯测试（top-quota、滞回保留/让位）全过；查证两池分离：`open_idle_session` 走 `_connect()` 不取 permit，`probe_folder_status` 走 `_connect_with_permit()`；`worker/main.py:schedule_periodic_inbox_sync` 新增 held 账号跳过。注：manager 级配额 DB 测试在 unit 模式 skip，其断言已逐行查证。
- AC-006：trust_prior — 代码路径已查证（候选查询排除 sync_enabled=false 与 paused、指纹变化关闭 watch、blocked 按指纹解除），但「禁用后会话关闭」的行为断言在 DB 测试 `test_ac006_disabled_account_session_closed`，unit 模式 skip，未能独立复跑。
- AC-007：re_verified — 查证隔离结构：`_reconcile_loop` 全捕获异常、worker `run()` 对 watcher 启动失败仅记日志、两个新模块均不写 Account.sync_status（grep 实证），反复失败只落 `backoff`/`fallback` 状态。
- AC-008：trust_prior — 巡检查询覆盖面已查证（全部 sync_enabled 账号的非 paused、非 inbox 文件夹；inbox 由 t057 既有逻辑覆盖，符合 spec 范围区「探测巡检覆盖其余文件夹」），但周期覆盖的行为断言在 DB 测试，unit 模式 skip，未能独立复跑。
- AC-009：re_verified — 复跑纯比较逻辑测试 `changed_dimensions`（含缺 UIDNEXT 回退）全过；查证 patrol 中 `is_changed` 为假时只更新基线、不入队。DB 层零入队断言同在 skip 的 DB 测试中，已逐行查证其断言内容。
- AC-010：trust_prior — 查证变化时以 priority=75、既有去重键入队 delta 且基线随后更新；「经既有管线收敛落库」的 DB 断言在 skip 的 DB 测试，未能独立复跑。
- AC-011：re_verified — 查证两条新路径均以 `sync_status != PAUSED` 过滤；且既有 `sync/engine.py` 证实 \Noselect 与 Gmail 虚拟标签文件夹在库中恒为 PAUSED（engine.py:351,371），远端消失文件夹亦然，故排除成立。
- AC-012：re_verified — 查证 patrol 的 `is_changed` 要求 `baseline is not None and cp.full_scan_complete`，无基线文件夹仅写 `last_status`/`last_probe_at`、不入队、不触发全量扫描；SyncCheckpoint 其余字段均有 server_default，新建检查点行不会触发非空约束失败。
- AC-013：re_verified — 直接查证选择逻辑代码并发现违反其上界保证的反例，即 finding f001（失败文件夹不推进探测时刻 + `max_unprobed_s` 无消费点）；轮转的正向部分（最久未探测优先 + 单轮上限截断）代码存在。
- AC-014：re_verified — 查证失败隔离部分成立（单夹异常仅记日志与计数、不中断整轮、不写账号状态）；但「后续周期重新探测」的节奏部分被 f001 证伪（实际每 60 秒 sweep 重试）。
- AC-015：re_verified — 复跑 `test_t061_config.py` 全部用例（默认值、env 覆盖、非法值拒绝）通过；查证两开关关闭路径：watcher `start()` 在 disabled 时直接返回、patrol 在 disabled 时返回空结果、held 集合为空使 t057 轮询恢复全量。
- AC-016：trust_prior — [deploy] 项；背景说明仅有本地 fake IMAP 服务器替代验证，真实账号部署实测记录未见产出，依赖实施侧/部署侧证据。

coverage = 10/16（re_verified 10 条 / 共 16 条）
建议合并前人工抽查 trust_prior 项（占比 37.5% > 30%）：重点抽查 AC-002、AC-006、AC-008、AC-010 的 DB 集成断言（需带 DB 环境复跑 DB 测试）与 AC-016 的部署实测记录。

verdict: FAIL

## Round 2 (2026-10-28T05:12:25+08:00)

reviewed_scope: af5318521a345e7a

### 前轮 finding 复核

- t061_code_f001（important）— **已消除**。以当前代码为准逐条核实：`src/mail_core/sync/patrol.py:160-180` 新增 `_record_attempt`，统一推进 `cursor["last_probe_at"]`，失败时累计 `last_probe_failures`、成功时清除；四条失败路径全部经它落账——provider 构建失败（patrol.py:196-208）、同账号已缓存的 provider 错误（patrol.py:186-190）、`probe_folder_status` 抛异常（patrol.py:210-223）、`status is None`（patrol.py:224-231）；成功路径 patrol.py:234 以 `failed=False` 调用。失败文件夹因此按 `interval_s`（默认 1200s）才重新 due，不再每 60 秒 sweep 重试，注释与行为一致。轮转上界：patrol.py:145-152 的 `_rotation_key` 新增 critical 优先组（从未探测，或距上次尝试超过 `config.max_unprobed_s` 者排前组内按 last_epoch 升序），`max_unprobed_s` 在调度逻辑中有真实消费点，不再是死配置；配合失败推进尝试时钟，失败集不再垄断每轮名额（回归用例 `test_ac013_ac014_failing_folders_do_not_starve_others` 与 `test_ac014_probe_failure_isolated_per_folder` 的断言已逐行查证，均为 DB 门控、本机 skip）。原 f001 的两条失败场景均无残留路径。
- t061_code_f002（minor）— **已消除**。patrol.py:104-121 初始查询已改为 `select(Folder, Account, SyncCheckpoint)` 单次 join（Account 内连接 + SyncCheckpoint 按 `(account_id, folder_id)` outerjoin），循环内不再逐文件夹 `session.get`。已核 `SyncCheckpoint` 主键即 `(account_id, folder_id)` 复合主键（`src/mail_core/mail/storage/models.py:271-272`），outerjoin 不会产生重复 Folder 行，无行为副作用。

### 本轮新发现

### t061_code_f003 - idle_watcher 的 blocked 3600 秒过期重试在主场景不可达：watch 线程以 IdleNotSupportedError / PermanentAuthError 退出后其 _Watch 条目永久残留 _watches，reconcile 的 open 循环在查 _blocked 之前先 continue，指纹不变时账号永不恢复 IDLE

- 严重度：important
- 锚点：违反 AC-006「条件恢复后 IDLE 自动重新建立」；失败场景：服务器起初不宣告 IDLE（或发生 PermanentAuthError）后条件在带外恢复——服务器后来宣告 IDLE、服务端解除认证锁定、或凭据经带外方式修复而指纹不变（`src/mail_core/accounts/service.py:158` 凭据更新只回写同值 `credential_ref`，同值赋值不弄脏 Account 行、`updated_at` 的 onupdate 不触发，指纹三要素均可不变）——该账号在 Worker 重启或发生席位/指纹变动之前永不重建 IDLE，与 idle_watcher.py:39-42 注释宣称的「指纹不变时 3600 秒后重试、带外修复不致永久 blocked」恰好相反。
- 位置：`src/mail_core/sync/idle_watcher.py:365-377`（`_watch_loop` 在两种 blocked 异常下写 `_blocked` 后 `return`，不注销自身 `_Watch`）、`idle_watcher.py:238-257`（open 循环先 `if account_id in self._watches: continue`，其后的 `_blocked` 过期判断永不执行）、`idle_watcher.py:224-236`（close 循环仅在失去席位 / 候选消失 / 指纹变化时才移除 watch，三者皆不发生时死条目永久残留，并继续以 incumbent 身份进入 `select_idle_holders` 的滞回计算）
- 问题：内存复现已实证（fake session 工厂恒抛 IdleNotSupportedError、内存 session 工厂 + 桩 `_load_candidates`）：首轮 reconcile 后工厂调用 1 次、状态落 fallback、watch 线程已退出但条目仍在 `_watches`；把 `_blocked` 时间戳人为老化 7200 秒（>3600）后再跑 `_reconcile_once()`，工厂调用仍为 1 次、`_blocked` 条目原样未动、状态仍 fallback——过期重试逻辑只在 watch 已因其他原因被移除时才可达，在其声称要解决的「指纹不变 + 账号持续 desired」主场景中是死代码。影响面限于降级为 t057 轮询（无数据丢失、账号不被误标 failed），但 AC-006 的自动恢复承诺在该场景不成立。
- 建议：让 blocked 退出路径注销自身 watch（`_watch_loop` 写 `_blocked` 后从 `_watches` 移除自身条目，或 reconcile 在 open 循环前先清理线程已死的 watch 条目），使指纹变化与 3600 秒过期两条重试路径真实可达；补一条不依赖 DB 的 manager 级用例覆盖「blocked 老化后同指纹重试」。

## 结论

- 前轮 finding 复核：f001 已消除、f002 已消除（均以当前代码逐行核实，未采信处置自述）；Round 1 结论段的指纹旁路低置信观察，其缓解措施（blocked 3600 秒过期）经复核修不彻底，缺陷形态见本轮 f003。
- 本轮新发现：1 条（important 1、minor 0、critical 0）
- 未进表的提示：Round 1 已提示的文件过大（idle_watcher.py 现 482 行、imap.py 维持大文件）与圈复杂度问题本轮修复未恶化亦未改善，维持结论段提示性质；`git status` 中未跟踪的 `src/desktop/node_modules/` 与本 task 无关，未纳入审查。
- 回归实测：t061 五个测试文件 unit 模式复跑 24 passed / 17 skipped（DB 门控，与本机无 DB 的既有约束一致）；后端 unit 全量 1499 passed / 22 failed / 305 skipped——22 条失败已在 anchor `327acc02` 的干净克隆上定向复跑，22/22 在 base 同样失败，与当前失败集逐条一致，修复零新增失败（Round 1 报告记为 20 条，本轮以自测对照为准，差异属基线环境口径，不归因于本 task 修复）。
- 总体判断：Round 1 两条 finding 均真实消除，但本轮修复为指纹旁路观察引入的 blocked 过期重试在主场景不可达，构成新的 important（f003），故本轮 FAIL。
- 系统性 follow-up：无（f003 为本 task 内修复，不另立项）

## AC 复验方式

- AC-001：trust_prior — 能力门控与候选过滤代码本轮修复未触及，依赖 Round 1 复验（fake IMAP 测试复跑 + 代码查证）；注：服务器在初次门控之后才宣告 IDLE 的恢复场景受 f003 影响。
- AC-002：trust_prior — 依赖 Round 1 证据（provider 层推送信号已复跑；DB 全链路断言在 unit 模式 skip）。
- AC-003：trust_prior — 退避纯逻辑本轮未触及，依赖 Round 1 复跑证据。
- AC-004：re_verified — 本轮全量重读 patrol.py 与 idle_watcher.py，两条新路径仍只写 SyncCheckpoint.cursor / AppSetting 状态与 enqueue_job，无 messages / message_bodies 写入（grep 实证）。
- AC-005：trust_prior — 配额/滞回/两池分离代码本轮未触及，依赖 Round 1 复验；附带观察：f003 的死 watch 条目会以 incumbent 身份参与滞回计算，但其状态非 LIVE，不占用 held 集合、不跳过轮询。
- AC-006：re_verified — 代码查证 + 内存复现：禁用/paused/指纹变化的关闭与恢复路径成立；但指纹不变的带外恢复场景被 f003 证伪（blocked 老化 7200 秒后 reconcile 仍不重试，工厂调用恒为 1）。
- AC-007：trust_prior — 隔离结构本轮未触及，依赖 Round 1 查证；f003 场景下账号状态停留在 fallback、未被误标 failed，此点已由本轮复现顺带证实。
- AC-008：trust_prior — 巡检覆盖面查询本轮仅按 f002 改为 join 形态，覆盖条件逐字未变；行为断言为 DB 门控，依赖 Round 1 查证。
- AC-009：re_verified — `changed_dimensions` 纯逻辑用例在本轮 t061 测试复跑中通过（24 passed 含该组）；无变化不入队的代码路径已随 patrol.py 全量重读复核。
- AC-010：trust_prior — 入队代码路径随 patrol.py 重读未见变化；DB 收敛断言 skip，依赖 Round 1 查证。
- AC-011：re_verified — patrol 查询仍以 `Folder.sync_status != PAUSED` 过滤（patrol.py:115-119），idle 候选过滤未变；排除口径与 Round 1 一致。
- AC-012：re_verified — patrol.py:237-244 重读确认：`is_changed` 仍要求基线存在且 `full_scan_complete` 为真，无基线文件夹仅记录 `last_status`、不入队。
- AC-013：re_verified — 选择逻辑逐行重读（due 判定 patrol.py:125-142、critical 优先轮转 patrol.py:145-152、cap 截断 patrol.py:153）；`max_unprobed_s` 现有真实消费点，原饿死反例已随 f001 消除。
- AC-014：re_verified — 四条失败路径逐行核实均经 `_record_attempt` 推进尝试时钟并累计失败计数（patrol.py:186-231），失败隔离与「后续周期重探」节奏成立；DB 回归用例断言已逐行查证（本机 skip）。
- AC-015：re_verified — `test_t061_config.py` 在本轮 t061 测试复跑中全部通过；两开关关闭路径本轮未触及，维持 Round 1 查证结论。
- AC-016：trust_prior — [deploy] 项，依赖实施侧/部署侧证据，本机仅有 fake IMAP 本地替代验证。

coverage = 7/16（re_verified 7 条 / 共 16 条）
建议合并前人工抽查 trust_prior 项（占比 56.25% > 30%）：重点抽查 AC-002、AC-008、AC-010 的 DB 集成断言（需带 DB 环境复跑 DB 测试）与 AC-016 的部署实测记录。

verdict: FAIL

## Round 3 (2026-10-28T05:17:58+08:00)

reviewed_scope: cc30dc1068156a48

### 前轮 finding 复核

- t061_code_f001（important）— **仍已消除**。本轮重读 `src/mail_core/sync/patrol.py` 现行代码：四条失败路径（patrol.py:175、191、207、214）与成功路径（patrol.py:219）仍全部经 `_record_attempt` 推进 `last_probe_at` 并维护失败计数；`_rotation_key`（patrol.py:140-145）仍消费 `config.max_unprobed_s` 做 critical 优先轮转。本轮修复未触及 patrol.py，无回归。
- t061_code_f002（minor）— **仍已消除**。patrol.py:104-121 仍为 `select(Folder, Account, SyncCheckpoint)` 单次 join + outerjoin 检查点，循环内无逐文件夹 `session.get`，无回归。
- t061_code_f003（important）— **已消除**。以当前代码与独立内存复现为准逐项核实：
  - 修复形态属实：`src/mail_core/sync/idle_watcher.py:406-419` 新增 `_register_blocked`，在同一把锁内写 `_blocked`、以身份判等（`self._watches.get(...) is watch`）注销自身 `_Watch` 条目、并直接写 `_states[account_id]="fallback"`（不经 `_set_state` 的成员守卫，注销后状态仍可落定）；`_watch_loop` 的两条 blocked 异常路径（idle_watcher.py:350-355，`IdleNotSupportedError` / `PermanentAuthError`）已统一走它，无遗漏的第三条 blocked 退出路径。`PermanentAuthError` 的类同一性已核：factory 侧由 `src/mail_core/providers/imap.py:781` 抛出 `mail_core.providers.http.PermanentAuthError`，与 watcher 捕获的是同一个类。
  - 过期重试可达（独立复现，非采信实施侧自述）：内存 session 工厂 + 桩 `_load_candidates`，工厂恒抛 `PermanentAuthError`——首轮 reconcile 后 watch 已注销、`_states` 为 fallback、工厂调用 1 次；同指纹未老化再跑一轮，调用仍为 1 次；把 `_blocked` 时间戳老化 7200 秒并令服务器恢复后，再跑一轮即重新 `_open_watch` 并进入 idling（与新增回归测试 `test_blocked_watch_deregisters_and_retries_after_expiry` 的 IdleNotSupportedError + 老化路径互为旁证，该测试在本轮 t061 复跑中通过）。
  - 指纹变化重试可达（独立复现）：blocked 未老化时把候选指纹换为新值，下一轮 reconcile 立即清除 `_blocked` 并重开 watch 进入 idling，两条重试路径均真实可达。
  - 注销后状态呈现正确：blocked 账号 `held_account_ids()` 为空（`_LIVE_STATES` 不含 fallback 且已不在 `_watches`），不跳过 t057 收件箱轮询；`_publish_state` 快照中该账号仍呈现 `fallback`（复现证实），AC-006 的自动退化与可观测均成立。
  - 滞回 incumbent 影响已核：注销后 blocked 账号不再进入 `select_idle_holders` 的 `current_holders`，不再以死条目占席——这正是期望语义（blocked 账号本就没有长连接）；其 desired 席位在其余账号间按原滞回规则分配，无新增 churn 路径（见下 f005 的状态残留问题仅限状态面，不涉及席位）。

### 本轮新发现

### t061_code_f004 - _register_blocked 的身份守卫只护 _watches：已被替换的陈旧 watch 线程仍可覆写新 watch 的 _states 与 _blocked

- 严重度：minor
- 锚点：行为缺陷（并发时序）+ 失败场景：watch 线程卡在 `idle_session_factory` 内（IMAP 连接超时默认 60 秒，`src/mail_core/providers/imap.py:672,747`）时，reconcile 因指纹变化/席位变化调 `_close_watch`，其 `join(timeout=5.0)`（idle_watcher.py:403）必然先于连接超时返回，reconcile 随即为同账号开新 watch；旧线程随后以 `PermanentAuthError`（imap.py:781）或 `IdleNotSupportedError` 退出并调 `_register_blocked(旧 watch)`——`_watches` 因身份判等保住新条目，但 `_blocked` 与 `_states` 被无条件覆写为旧指纹与 `fallback`。
- 位置：`src/mail_core/sync/idle_watcher.py:415-419`（`_register_blocked` 内 `_blocked` / `_states` 两处写无身份守卫；对照同函数 417-418 行对 `_watches` 的 `is watch` 守卫）
- 问题：内存复现已证实机制：预置新 watch（state=idling）后以陈旧 watch 调 `_register_blocked`，`_watches` 条目保全，但 `_states` 被改为 `fallback`、`_blocked` 被写为旧指纹与当前时刻。后果有界：新 watch 下一次状态迁移即覆回 `_states`；`_blocked` 旧指纹在下次 open 时因指纹不符被清除；同指纹子情形（席位让位后重得席位）下，陈旧时间戳可能使账号在新 watch 以 stop_event 正常退出后被无谓推迟至多 3600 秒才重建 IDLE。期间账号维持 t057 轮询、不被误标 failed、无数据影响，故定 minor。
- 建议：把守卫扩到全部三处写：仅当 `_watches.get(account_id) is watch` 或该账号当前无注册 watch 时才写 `_blocked` / `_states`；已被替换的陈旧线程直接返回。

### t061_code_f005 - 注销后 blocked 账号退出候选集时其 _states / _blocked 条目永不清理，状态面长期残留 fallback

- 严重度：minor
- 锚点：行为缺陷（状态一致性/资源残留）+ 失败场景：账号先进入 blocked（已按 f003 修复注销 watch），随后被禁用、收件箱变 paused 或被删除而退出 `_load_candidates` 候选集——此后该账号的 `fallback` 状态与 `_blocked` 条目在 Worker 进程存续期内永不清除，`worker:idle_state` 持续对外发布一个已禁用/已删除账号的 watcher 状态。
- 位置：`src/mail_core/sync/idle_watcher.py:224-236`（close 循环只遍历 `_watches` 并在其中 pop `_states`，已注销的 blocked 账号不在其内）、`idle_watcher.py:406-419`（`_register_blocked` 写 `_states` 后再无任何清理路径触及该条目）
- 问题：内存复现已证实：blocked 落定后清空候选集再跑 `_reconcile_once()`，`snapshot()` 仍含该账号 `fallback`、`_blocked` 条目仍在。修复 f003 前，死 watch 条目留在 `_watches`，候选消失时 close 循环会顺带 pop 其状态；注销修复移除了这条唯一的清理路径却未补替代清理。影响限于状态面失真与每账号一条的内存残留（有界于账号总量），同步行为本身正确（无连接、无入队、轮询不受影响），故定 minor。
- 建议：在 reconcile 中对「不在候选集且不在 `_watches`」的账号顺带清除其 `_states` / `_blocked` 残留条目（或在 close 循环之外加一段残留状态清扫），使状态面与候选集保持一致。

## 结论

- 前轮 finding 复核：f001、f002 仍已消除（patrol.py 本轮未被修复触及，逐行复核无回归）；f003 已消除——`_register_blocked` 注销逻辑属实，过期（3600 秒）与指纹变化两条重试路径经独立内存复现证实真实可达（分别覆盖 `PermanentAuthError` 与指纹变更场景），注销后 state 正确呈现 fallback、held 集合为空、不影响 t057 轮询。
- 本轮新发现：2 条（minor 2、important 0、critical 0），均为 f003 修复的伴生残留：f004 陈旧线程覆写未守卫、f005 注销后状态条目无清理路径；两者影响均有界且自愈/不涉及同步正确性，不阻断。
- 未进表的提示：文件过大维持 Round 1/2 结论段提示（`idle_watcher.py` 现 493 行、超实现源码 400 行 minor 阈值；`imap.py` 1617 行存量大文件），本轮修复仅净增约 11 行，未恶化到进表程度；圈复杂度无新增高分支函数（`_register_blocked` 为线性逻辑）；`git status` 中未跟踪的 `src/desktop/node_modules/` 与本 task 无关，未纳入审查。其余七视角（安全/契约·Breaking/性能·资源/架构/健壮性·可观测/文档·规格）本轮对修复 diff 已扫过：两条 blocked 路径无敏感信息落日志、无公开签名/配置键变更、无新增查询，`_register_blocked` 持锁区间仅字典操作、无 IO、无死锁面（`_close_watch` 在锁外 join，`stop()` 先清表再逐个 set stop_event，blocked 线程已先行 return，不存在 stop 漏唤醒的挂起线程——已逐行核实）。
- 回归实测：t061 六个测试文件以 `KKMAIL_TEST_MODE=unit` 独立复跑 29 passed / 17 skipped（skip 均为 DB 环境门控，与本机无 Docker、无可用 PG 的既有约束一致），含新增回归测试 `test_blocked_watch_deregisters_and_retries_after_expiry` 通过；本轮另行全量 unit 复跑失败计数 20 条，与实施侧基线口径（base `327acc02` 基线 20 failed）计数一致，未见 t061 相关失败混入（逐条失败集比对依赖实施侧受控复跑记录）。
- 总体判断：Round 2 的 blocking finding f003 已真实消除，本轮仅有两条 minor 伴生问题，按判定式本轮 PASS；f004/f005 仍须由 implementer 写入 task.md 处置表。
- 系统性 follow-up：无（f004/f005 均为本 task 内小修，不另立项）

## AC 复验方式

- AC-001：trust_prior — 能力门控与候选过滤代码本轮修复未触及，依赖 Round 1 复验（fake IMAP 测试复跑 + 代码查证）；初次门控后才宣告 IDLE 的恢复场景随 f003 消除而打通，已由本轮过期/指纹两条复现顺带覆盖其重试入口。
- AC-002：trust_prior — 依赖 Round 1 证据（provider 层推送信号已复跑；DB 全链路断言在 unit 模式 skip）。
- AC-003：trust_prior — 退避纯逻辑本轮未触及，依赖 Round 1 复跑证据；本轮复跑的 t061 测试组含退避用例且全过。
- AC-004：re_verified — 本轮修复 diff 逐行重读：`_register_blocked` 仅写 `_blocked` / `_watches` / `_states` 三处内存结构，idle_watcher 与 patrol 仍无 messages / message_bodies 写入。
- AC-005：re_verified — 查证注销后 blocked 账号退出 `current_holders` 与 held 集合（复现中 `held_account_ids()` 为空），不占 IDLE 席位、不占任务槽位、不跳过轮询；配额/滞回/两池分离其余代码未触及，t061 测试组中 holder 选择纯测试本轮复跑通过。
- AC-006：re_verified — 独立内存复现全覆盖本轮焦点：`PermanentAuthError` 与 `IdleNotSupportedError` 两路径均注销并落 fallback；同指纹未老化不重试；老化 7200 秒后同指纹重试成功；指纹变化立即重试成功；禁用/paused 的关闭路径维持 Round 2 查证（其状态残留问题见 f005，仅状态面、非连接行为）。
- AC-007：re_verified — 复现全程 blocked 账号状态恒为 fallback、未被标 failed，reconcile 循环在其余轮次正常推进；watcher 隔离结构本轮未触及。
- AC-008：trust_prior — 巡检覆盖面本轮未触及，依赖 Round 2 查证；行为断言为 DB 门控、本机 skip。
- AC-009：trust_prior — `changed_dimensions` 纯逻辑在本轮 t061 复跑中通过；无变化不入队的 DB 断言 skip，依赖 Round 2 查证。
- AC-010：trust_prior — 入队代码路径未变，DB 收敛断言 skip，依赖 Round 2 查证。
- AC-011：re_verified — patrol 与 idle 候选的 paused 过滤本轮逐行重读未变（patrol.py:115-119 与 `_load_candidates` 过滤条件）。
- AC-012：trust_prior — patrol 无基线分支本轮未触及，依赖 Round 2 逐行查证。
- AC-013：re_verified — 本轮重读 patrol.py:140-153：`_rotation_key` 的 critical 优先与 `max_unprobed_s` 消费点仍在，单轮上限截断未变，f001 消除状态保持。
- AC-014：re_verified — 本轮重读 patrol.py:148-219：四条失败路径与成功路径仍全部经 `_record_attempt` 落账，失败隔离与周期重探节奏保持。
- AC-015：trust_prior — 配置层本轮未触及，`test_t061_config.py` 在本轮复跑中通过；两开关关闭路径依赖 Round 1 查证。
- AC-016：trust_prior — [deploy] 项；本机仅有本地替代验证（本轮全量 unit 与 fake IMAP 证据），真实账号部署实测依赖实施侧/部署侧记录。

coverage = 8/16（re_verified 8 条 / 共 16 条）
建议合并前人工抽查 trust_prior 项（占比 50% > 30%）：重点抽查 AC-002、AC-008、AC-010 的 DB 集成断言（需带 DB 环境复跑 DB 测试）与 AC-016 的部署实测记录。

verdict: PASS

## Round 4 (2026-10-28T05:22:49+08:00)

reviewed_scope: 09a9b918fa3cf746

### 前轮 finding 复核

- t061_code_f001（important）— **仍已消除**。本轮 grep 复核 patrol.py 现行代码：`_rotation_key`（patrol.py:140-145）仍消费 `config.max_unprobed_s` 做 critical 优先轮转，四条失败路径仍经 `_record_attempt`（patrol.py:175、191、207 及 status-None 路径）推进尝试时钟；本轮修复未触及 patrol.py，无回归。
- t061_code_f002（minor）— **仍已消除**。patrol.py:107 仍为 `select(Folder, Account, SyncCheckpoint)` 单次 join，无逐文件夹 `session.get`，无回归。
- t061_code_f003（important）— **仍已消除**。`_register_blocked` 注销形态完整保留（见下 f004 复核中的 self 情形实测：当前 watch 自行 blocked 时注销 + 落 fallback + 记 blocked 指纹均正常）；新增回归测试 `test_blocked_watch_deregisters_and_retries_after_expiry` 在本轮 t061 复跑中通过，过期/指纹两条重试路径未被本轮修复破坏。
- t061_code_f004（minor）— **已消除**。以当前代码与独立内存复现为准：
  - 守卫覆盖三处写属实：`src/mail_core/sync/idle_watcher.py:427-437`，`_register_blocked` 全程持同一把锁，先取 `current = self._watches.get(...)`（428），`current is not None and current is not watch` 时直接 return（429-433），return 位于全部三处写之前——`_blocked` 写（434）、`_watches` 注销（435-436）、`_states` 写（437）无一可达；守卫与三处写在同一锁区间内完成，`_open_watch` 的注册与 `_close_watch` 的注销同样经该锁，不存在检查与写之间的 TOCTOU 绕过窗口。`_watch_loop` 的两条 blocked 退出路径（idle_watcher.py:361、364）仍是仅有的 `_register_blocked` 调用点，无第三条未守卫的 blocked 写路径。
  - 独立复现（本轮自写内存脚本，非采信实施侧测试）：预置 fresh watch（state=idling）后以 stale watch 调 `_register_blocked`——`_watches` 条目仍为 fresh、`_states` 仍 idling、`_blocked` 无条目；随后以 fresh 自身调用——正常注销、落 fallback、blocked 记 fp-new。新增测试 `test_register_blocked_stale_thread_cannot_clobber_new_watch`（test_t061_idle_watcher.py:402）断言与此一致且在本轮复跑中通过；另以「卡住的 factory 中途置 stop_event 后抛 IdleNotSupportedError」的完整 `_watch_loop` 时序作对照组，陈旧线程同样零覆写。
  - 已审的残留情形（不另列 finding）：`current is None`（替换者已先行注销）时陈旧线程仍会写 `_blocked`/`_states`——此为 Round 3 建议本身允许的语义（无注册 watch 时可写），且后果有界：指纹相同则仅刷新 blocked 时间戳（推迟量 ≤ 陈旧线程卡住时长），指纹不同则下轮 open 循环按指纹不符立即清除重试，不构成对新 watch 的覆写。
- t061_code_f005（minor）— **已消除**。以当前代码与独立内存复现为准：
  - 清扫形态属实：`src/mail_core/sync/idle_watcher.py:207-221`，`_reconcile_once` 在 `_load_candidates` 后、desired 计算与 close/open 循环之前，于锁内计算 `stale_ids = (set(_states) | set(_blocked)) - candidate_ids - set(_watches)`（217），逐个 pop 两表（218-220）。
  - 不误删已实测（本轮复现四情形）：（C1）已离候选集的 blocked 账号 reconcile 后 snapshot 与 `_blocked` 均清空（与新增测试 `test_reconcile_sweeps_blocked_state_for_departed_accounts` 一致）；（C2）**仍在候选集**的 blocked 账号——`_states=fallback` 与 `_blocked` 条目均保留、未被清扫，后续仍按 blocked 过期语义治理；(C3) 在 `_watches` 内但不在候选集的账号——清扫因 `- set(_watches)` 跳过它，本轮由 close 循环正常关闭并 pop 状态，其 `_blocked` 本轮保留、下一轮 reconcile 即被清扫清除，无提前误删、无永久残留；（C4）held/desired 且在候选集的 watch——条目、状态与 `held_account_ids()` 均无扰动。
  - 顺序安全：清扫取的是本轮候选快照与清扫瞬间 `_watches` 快照（同一锁内），清扫后 close 循环对新失去资格的 watch 仍走原有关闭 + pop 状态路径，清扫与 close/open 无交叉删除；被清账号若下轮重回候选集，按 AC-006 恢复语义重新参与选择/重试，属期望行为。

### 本轮新发现

### t061_code_f006 - _set_state 只查成员不查身份：陈旧 watch 线程仍可经通用异常/会话错误路径覆写新 watch 的 _states（f004 的同族绕过路径）

- 严重度：minor
- 锚点：行为缺陷（并发时序）+ 失败场景：与 f004 完全相同的时间线——watch 线程卡在 `idle_session_factory` 内时被 reconcile 以 `_close_watch` 替换（join 5 秒先于连接超时返回）并开出新 watch；陈旧线程随后不是以 blocked 异常、而是以通用异常（连接超时/OSError 等）退出 factory，或其已建立的会话以异常断开——两条路径都经 `_set_state(account_id, "backoff")` 写状态，而 `_set_state` 无身份判等，新 watch 的状态被覆写。
- 位置：`src/mail_core/sync/idle_watcher.py:450-453`（`_set_state` 仅判 `account_id in self._watches`）；无守卫调用点 idle_watcher.py:375（factory 通用异常）、381（连接成功后置 idling）、389/391（changed 前后）、406（会话异常置 backoff）
- 问题：独立复现已证实（内存脚本，factory 内先置陈旧 watch 的 stop_event 模拟「卡住期间被关闭替换」、再抛 RuntimeError 走 `_watch_loop` 真实路径）：新 watch 仍注册且原为 idling，复现后 `_states` 变为 `backoff`、`held_account_ids()` 变为空集；同时间线改抛 `IdleNotSupportedError` 的对照组则零覆写（f004 守卫有效）。后果有界：状态面失真（实际健康的 IDLE 被发布为 backoff）、held 假阴性使该账号收件箱轮询不被跳过（多一次发现通道，去重键保证不产生重复任务）；账号不被误标 failed、无数据影响；新 watch 下一次状态迁移（change/断开重连）即覆回，但纯超时续 IDLE 的循环不重设状态，故失真可跨多个 IDLE 周期存续，直至下一次变化或断线。故定 minor。
- 建议：把身份判等推广到 `_set_state`：调用点传入 watch 本人，函数内仅当 `self._watches.get(account_id) is watch` 时才写；与 `_register_blocked` 的守卫保持同一模式。

## 结论

- 前轮 finding 复核：f001、f002、f003 仍已消除（patrol 与注销主形态未被本轮修复触及，逐项复核无回归）；f004 已消除——守卫在同一锁内覆盖 `_blocked`/`_watches`/`_states` 三处写，无 TOCTOU 绕过，独立复现与新增白盒测试互证；f005 已消除——清扫条件「不在候选 且 不在 `_watches`」四情形实测安全（候选集内 blocked 不误删、held 不受扰、在册 watch 本轮走 close 路径、残留至多多留一轮即清）。
- 本轮新发现：1 条（minor 1、important 0、critical 0）——f006，f004 同族的 `_set_state` 身份缺口，非本轮修复引入（该函数形态自首轮即在），但在本轮「守卫绕过路径」专项复核中经真实 `_watch_loop` 时序复现证实；影响限于状态面与轮询跳过判定，不阻断。
- 未进表的提示：文件过大维持结论段提示性质——`idle_watcher.py` 现 510 行（超实现源码 400 行 minor 阈值，本轮净增约 17 行）、测试文件 `test_t061_idle_watcher.py` 656 行（超测试源码 600 行 minor 阈值）；未见由此直接导致的可观测缺陷。其余视角（安全/契约·Breaking/性能·资源/架构/健壮性·可观测/文档·规格）本轮对修复 diff 已扫过：清扫为纯内存字典操作、无新增查询/IO/日志敏感面，`_register_blocked` 锁区间仍仅字典操作、无死锁面；`git status` 中未跟踪的 `src/desktop/node_modules/` 与本 task 无关，未纳入审查。
- 回归实测：t061 六个测试文件以 `KKMAIL_TEST_MODE=unit` 独立复跑，结果 31 passed / 17 skipped，与实施侧口径一致（skip 均为 DB 环境门控；本机无 Docker、无可用 PG 的既有约束不变），含两条新增纯测试通过。全量 unit 回归本轮未独立复跑（本轮 diff 仅 idle_watcher 状态治理 + 两条纯测试，风险面由 t061 组与上述内存复现覆盖），此点如实披露。
- 总体判断：Round 3 两条 minor 均真实消除，本轮仅新发现一条同族 minor（f006），无未解决 critical/important，故本轮 PASS；f006 仍须由 implementer 写入 task.md 处置表。
- 系统性 follow-up：无（f006 为本 task 内小修，不另立项）

## AC 复验方式

- AC-001：trust_prior — 候选过滤与能力门控代码本轮未触及，依赖 Round 1 复验（fake IMAP 测试复跑 + 代码查证）；本轮 t061 复跑中相关用例通过。
- AC-002：trust_prior — 依赖 Round 1 证据（provider 层推送信号已复跑；DB 全链路断言在 unit 模式 skip）。
- AC-003：trust_prior — 退避纯逻辑本轮未触及，依赖 Round 1 复跑证据；本轮 t061 复跑含退避用例且全过。
- AC-004：re_verified — 本轮对 idle_watcher.py / patrol.py 全文 grep 与重读：两条新路径仍只写 SyncCheckpoint.cursor / 内存状态 / AppSetting 与 enqueue_job，无 messages / message_bodies 表写入（patrol.py:36 的 `"messages"` 仅为 STATUS 维度名字符串）。
- AC-005：re_verified — 本轮复现 C4 证实 held 集合在清扫下无扰动、配额/滞回/两池分离代码未触及；附注：f006 的 held 假阴性方向是「多轮询」而非超配额或占槽，不违反本条配额与两池不变量。
- AC-006：re_verified — 本轮独立复现覆盖：blocked 注销与 fallback 落定（f003/f004 self 情形）、候选集内 blocked 不被清扫误伤（C2）、离候选集后状态与 blocked 残留被清扫（C1/C3），禁用/paused/删除后的状态面一致性随 f005 消除而补齐；连接关闭/恢复的 DB 断言仍为 skip，依赖前轮查证。
- AC-007：re_verified — 本轮全部复现中 blocked/陈旧线程场景下账号状态恒为 fallback/backoff、从未被标 failed，reconcile 循环在其余轮次正常推进；f006 的状态失真不涉及 failed 标记。
- AC-008：trust_prior — 巡检覆盖面本轮未触及，依赖 Round 2 查证；行为断言为 DB 门控、本机 skip。
- AC-009：trust_prior — patrol 本轮未触及，`changed_dimensions` 纯逻辑在本轮 t061 复跑中通过；DB 零入队断言 skip，依赖 Round 2 查证。
- AC-010：trust_prior — 入队代码路径未变，DB 收敛断言 skip，依赖 Round 2 查证。
- AC-011：trust_prior — patrol 与 idle 候选的 paused 过滤维持 Round 3 逐行查证结论，本轮修复未触及过滤条件。
- AC-012：trust_prior — patrol 无基线分支本轮未触及，依赖 Round 2 逐行查证。
- AC-013：re_verified — 本轮 grep 复核 patrol.py:140-145：`_rotation_key` 的 critical 优先与 `max_unprobed_s` 消费点仍在，单轮上限与最久未探测优先未变。
- AC-014：re_verified — 本轮 grep 复核 patrol.py:148-231 区间：失败路径仍经 `_record_attempt` 落账（patrol.py:175、191、207 等），失败隔离与周期重探节奏保持。
- AC-015：trust_prior — 配置层本轮未触及，`test_t061_config.py` 在本轮复跑中通过；两开关关闭路径依赖 Round 1 查证。
- AC-016：trust_prior — [deploy] 项；本机仅有本地替代验证（本轮 t061 复跑与 fake IMAP 证据），真实账号部署实测依赖实施侧/部署侧记录。

coverage = 6/16（re_verified 6 条 / 共 16 条）
建议合并前人工抽查 trust_prior 项（占比 62.5% > 30%）：重点抽查 AC-002、AC-008、AC-010 的 DB 集成断言（需带 DB 环境复跑 DB 测试）与 AC-016 的部署实测记录。

verdict: PASS

## Round 5 (2026-10-28T05:26:07+08:00)

reviewed_scope: adcd88696bca5dd2

### 前轮 finding 复核

- t061_code_f001（important）— **仍已消除**。本轮 grep 复核 patrol.py 现行代码：四条失败路径与成功路径仍经 `_record_attempt` 落账（patrol.py:175、191、207、214、219），`_rotation_key`（patrol.py:140-145）仍消费 `config.max_unprobed_s` 做 critical 优先轮转；本轮修复未触及 patrol.py，无回归。
- t061_code_f002（minor）— **仍已消除**。patrol.py:107 仍为 `select(Folder, Account, SyncCheckpoint)` 单次 join，无逐文件夹 `session.get`，无回归。
- t061_code_f003（important）— **仍已消除**。`_register_blocked` 注销形态完整保留（idle_watcher.py:416-437），本轮 t061 复跑中 `test_blocked_watch_deregisters_and_retries_after_expiry` 通过，过期/指纹两条重试路径未被本轮修复破坏。
- t061_code_f004（minor）— **仍已消除**。`_register_blocked` 的身份守卫（idle_watcher.py:428-433，`current is not None and current is not watch` 时在全部三处写之前 return）与 Round 4 复核形态逐字一致；扩展后的白盒测试中 `_register_blocked(stale)` 断言（test_t061_idle_watcher.py:432-435）仍在且通过。
- t061_code_f005（minor）— **仍已消除**。reconcile 残留清扫仍在（idle_watcher.py:207-221，`stale_ids = (set(_states) | set(_blocked)) - candidate_ids - set(_watches)` 锁内 pop 两表），本轮修复未触及，无回归。
- t061_code_f006（minor）— **已消除**。以当前代码与独立内存复现为准逐项核实：
  - 签名与守卫属实：`src/mail_core/sync/idle_watcher.py:450-459`，`_set_state(self, watch, state)` 在同一把锁内仅当 `self._watches.get(watch.account_id) is watch` 时才写 `_states`——与 `_register_blocked`（idle_watcher.py:428-433）的身份判等为同一守卫模式（差异仅在 blocked 版对 `current is None` 允许写自身 fallback，而 `_set_state` 对无注册 watch 不写，与修复前成员检查 `account_id in self._watches` 的语义一致，无行为回退）。
  - 全部调用点已改传 watch 本人：全仓 grep（src/tests/scripts）`_set_state` 仅 5 个生产调用点——idle_watcher.py:375（factory 通用异常 backoff）、381（idling）、389（changed）、391（changed 后 idling）、406（会话异常 backoff），无遗漏的旧签名 `(account_id, state)` 调用；仓库其余命中仅 `.scratch/idle_watcher.fixed.py` 草稿副本（gitignore、非交付代码）与本报告自身。
  - 公开面无波及：`_set_state` 为私有方法（下划线前缀），除上述内部调用点外唯一外部引用是白盒测试；无 API/CLI/配置键/schema 变更。
  - `_states` 全部写点已穷尽核查：除 `_set_state`（459）与 `_register_blocked`（436）两处守卫写外，仅剩 reconcile open 循环的 blocked-fallback 写（260，锁内且以「不在 `_watches`」为前提）与 `_open_watch` 注册时的 connecting 写（341，锁内、写自己刚注册的 watch），均非 watch 线程路径、无陈旧覆写面。
  - 独立复现（本轮自写内存脚本，经真实 `_watch_loop` 路径、stop_event 由 factory/会话内部置位以模拟「卡住期间被 `_close_watch` 替换」）：（A）陈旧线程 factory 通用异常路径——新 watch 条目、idling 状态与 `held_account_ids()` 均无扰动；（B）陈旧线程会话异常路径（idling→异常→backoff 两次写）——同样零覆写；（C）对照组 fresh watch 自身走会话异常路径——状态正常遷移至 backoff，守卫未过度拦截；（D）无注册 watch 的 `_set_state` 不写（与旧成员检查语义一致）。四情形全过；扩展白盒测试 `test_register_blocked_stale_thread_cannot_clobber_new_watch`（test_t061_idle_watcher.py:436-442 新增 f006 段：stale 写 backoff 后状态仍 idling、fresh 可正常写 changed/idling）在本轮 t061 复跑中通过，断言与复现互证。

### 本轮新发现

无（0 条）。本轮对 `_set_state` 签名变更的波及面、守卫一致性与 `_states` 全部写点穷尽扫描后，未发现新的 critical / important / minor 问题。

## 结论

- 前轮 finding 复核：f001、f002、f003、f004、f005 仍全部已消除（逐项以现行代码锚点复核，本轮修复仅触及 idle_watcher 状态写路径与一条白盒测试扩展，未波及 patrol 与 blocked/清扫逻辑）；Round 4 唯一新 finding f006 已消除——身份守卫已推广到 `_set_state` 全部 5 个调用点，与 `_register_blocked` 同一模式，独立复现证实 f004 同族绕过路径（通用异常/会话错误两条）均已封堵且 fresh watch 正常遷移不受影响。至此 f001–f006 六条 finding 全部消除，无未解决项。
- 本轮新发现：0 条
- 未进表的提示：文件过大维持结论段提示性质——`idle_watcher.py` 现 516 行（超实现源码 400 行 minor 阈值，本轮净增约 6 行）、测试文件 `test_t061_idle_watcher.py` 662 行（超测试源码 600 行 minor 阈值）；未见由此直接导致的可观测缺陷，按降级规则不进表。其余视角（安全/契约·Breaking/性能·资源/架构/健壮性·可观测/文档·规格）本轮对修复 diff 已扫过：`_set_state` 锁区间仅字典写、无 IO/日志/新查询，私有签名变更无公开面影响；`git status` 中未跟踪的 `src/desktop/node_modules/` 与本 task 无关，未纳入审查。
- 回归实测：t061 六个测试文件以 `KKMAIL_TEST_MODE=unit` 独立复跑，结果 31 passed / 17 skipped，与实施侧口径一致（skip 均为 DB 环境门控；本机无 Docker、无可用 PG 的既有约束不变），含 f006 扩展断言的白盒测试通过；另以自写内存脚本经真实 `_watch_loop` 时序复现 f006 四情形全过。全量 unit 回归本轮未独立复跑（本轮 diff 仅 `_set_state` 守卫 + 测试扩展，风险面由 t061 组与上述复现覆盖），此点如实披露。
- 总体判断（最终全量结论）：五轮评审累计 6 条 finding（important 2：f001、f003；minor 4：f002、f004、f005、f006）已全部经独立复核确认消除，无未解决 critical / important，本轮亦无新发现；仅剩文件过大两项结论段提示（非阻断）。按判定式，最终 verdict 为 PASS。
- 系统性 follow-up：无

## AC 复验方式

- AC-001：trust_prior — 候选过滤与能力门控代码本轮未触及，依赖 Round 1 复验（fake IMAP 测试复跑 + 代码查证）；本轮 t061 复跑中相关用例通过。
- AC-002：trust_prior — 依赖 Round 1 证据（provider 层推送信号已复跑；DB 全链路断言在 unit 模式 skip）。本轮复现顺带证实 changed 路径的状态写（389/391）经守卫后对当前 watch 仍正常生效。
- AC-003：trust_prior — 退避纯逻辑本轮未触及，依赖 Round 1 复跑证据；本轮 t061 复跑含退避用例且全过；复现 A/C 证实 backoff 状态写在守卫下对当前 watch 正常、对陈旧线程拦截。
- AC-004：re_verified — 本轮对 idle_watcher.py / patrol.py 全文 grep 复核：两条新路径仍只写 SyncCheckpoint.cursor / 内存状态 / AppSetting 与 enqueue_job，无 messages / message_bodies 表写入（patrol.py:36 的 `"messages"` 仅为 STATUS 维度名字符串）。
- AC-005：re_verified — 本轮复现 A/B 证实陈旧线程覆写消除后 `held_account_ids()` 不再出现 f006 的假阴性（新 watch idling 时 held 恒含该账号）；配额/滞回/两池分离代码未触及，t061 复跑中 holder 选择纯测试通过。
- AC-006：re_verified — 本轮复核覆盖：`_register_blocked` 注销与重试（f003/f004 形态逐字未变、白盒测试通过）、离候选集残留清扫（f005 代码锚点未变）、陈旧线程不再覆写新 watch 的状态面（f006）；连接关闭/恢复的 DB 断言仍为 skip，依赖前轮查证。
- AC-007：re_verified — 本轮全部复现中 blocked/陈旧线程/会话异常场景下账号状态恒为 fallback/backoff、从未被标 failed，reconcile 与 `_watch_loop` 在守卫下正常推进；watcher 隔离结构未触及。
- AC-008：trust_prior — 巡检覆盖面本轮未触及，依赖 Round 2 查证；行为断言为 DB 门控、本机 skip。
- AC-009：trust_prior — patrol 本轮未触及，`changed_dimensions` 纯逻辑在本轮 t061 复跑中通过；DB 零入队断言 skip，依赖 Round 2 查证。
- AC-010：trust_prior — 入队代码路径未变，DB 收敛断言 skip，依赖 Round 2 查证。
- AC-011：trust_prior — patrol 与 idle 候选的 paused 过滤维持 Round 3 逐行查证结论，本轮修复未触及过滤条件。
- AC-012：trust_prior — patrol 无基线分支本轮未触及，依赖 Round 2 逐行查证。
- AC-013：re_verified — 本轮 grep 复核 patrol.py:140-145：`_rotation_key` 的 critical 优先与 `max_unprobed_s` 消费点仍在，单轮上限与最久未探测优先未变。
- AC-014：re_verified — 本轮 grep 复核 patrol.py:175、191、207、214、219：失败与成功路径仍全部经 `_record_attempt` 落账，失败隔离与周期重探节奏保持。
- AC-015：trust_prior — 配置层本轮未触及，`test_t061_config.py` 在本轮复跑中通过；两开关关闭路径依赖 Round 1 查证。
- AC-016：trust_prior — [deploy] 项；本机仅有本地替代验证（本轮 t061 复跑与 fake IMAP 证据），真实账号部署实测依赖实施侧/部署侧记录。

coverage = 6/16（re_verified 6 条 / 共 16 条）
建议合并前人工抽查 trust_prior 项（占比 62.5% > 30%）：重点抽查 AC-002、AC-008、AC-010 的 DB 集成断言（需带 DB 环境复跑 DB 测试）与 AC-016 的部署实测记录。

verdict: PASS

## Round 6 (2026-10-28T05:39:46+08:00)

reviewed_scope: 56fefa3627511b3d

本轮为证据修复轮：对已提交的单一执行 commit `8016faa4a95d996282ec1168e15b6ad6a02b1a57`（first parent `327acc0250f26c71d7ad2b777e876b92ff79c484`）的实际交付字节做确认性重审，核对 Round 1–5 的 PASS 结论对已提交内容仍然成立。上方 reviewed_scope 按工具链算法对该 commit tip 计算。审阅由独立 reviewer 只读执行，对象为 commit 中的字节，非 worktree 未提交状态。

### 前轮 finding 复核

- f001（important）— 已消除。`src/mail_core/sync/patrol.py:148-169` 的 `_record_attempt` 统一推进 `last_probe_at` 并维护失败计数；全部失败路径（同账号 provider 错误 `patrol.py:175`、provider 构建失败 `patrol.py:191`、探测抛异常 `patrol.py:207`、`status is None` `patrol.py:214`）与成功路径（`patrol.py:219`）均经它落账。`patrol.py:140-143` 的 `_rotation_key` 以「从未探测或距上次尝试超过 `config.max_unprobed_s`」为 critical 优先组、`max_unprobed_s` 有真实消费点。
- f002（minor）— 已消除。`src/mail_core/sync/patrol.py:105-121` 初始查询为 `select(Folder, Account, SyncCheckpoint)` 单次 join（Account 内连接 + SyncCheckpoint 按 `(account_id, folder_id)` outerjoin），循环内无逐文件夹 `session.get`。
- f003（important）— 已消除。`src/mail_core/sync/idle_watcher.py:416-436` 的 `_register_blocked` 在锁内写 `_blocked[account_id] = (watch.fingerprint, time.monotonic())`（`idle_watcher.py:433`）、注销自身 `_Watch` 条目（`idle_watcher.py:434-435`）并落 `fallback` 状态（`idle_watcher.py:436`）；配合 `_BLOCKED_RETRY_S = 3600.0`（`idle_watcher.py:43`）与 open 循环的指纹变化/过期重试判断（`idle_watcher.py:253-263`），两条重试路径可达。两条 blocked 退出路径（`idle_watcher.py:361,364`）均经它，无遗漏。
- f004（minor）— 已消除。`src/mail_core/sync/idle_watcher.py:425-432` 的 `_register_blocked` 先取 `current = self._watches.get(...)`，`current is not None and current is not watch` 时在全部三处写之前直接 return，陈旧线程不能覆写新 watch 的 `_blocked`/`_watches`/`_states`。
- f005（minor）— 已消除。`src/mail_core/sync/idle_watcher.py:207-220` 的 `_reconcile_once` 在候选加载后、desired 计算前，于锁内以 `stale_ids = (set(_states) | set(_blocked)) - candidate_ids - set(_watches)` 清扫不在候选集且不在 `_watches` 的残留 `_states`/`_blocked` 条目。
- f006（minor）— 已消除。`src/mail_core/sync/idle_watcher.py:450-459` 的 `_set_state(self, watch, state)` 在锁内仅当 `self._watches.get(watch.account_id) is watch` 时才写 `_states`；全部 5 个生产调用点均改传 watch 本人（`idle_watcher.py:375,381,389,391,406`），无旧 `(account_id, state)` 签名残留。

### 本轮新发现

无（0 条）。对已提交 diff 新扫了 `idle_watcher.py`、`patrol.py`、`providers/imap.py`、`providers/base.py`、`worker/main.py`、`config/models.py`/`loader.py`，未发现新的 critical / important / minor 问题：IDLE 独立配额成立——`config/models.py:59` `idle_quota: int = 32` 与 `config/models.py:34` 的 `total_slots: int = 8` 为独立字段，`config/loader.py:104` 默认同为 32；热账号优先带滞回在 `idle_watcher.py:84-121` 的 `select_idle_holders`；不占任务槽位在代码层成立——`providers/imap.py:1585` 的 `open_idle_session` 走 `_connect()` 不取 permit、`providers/imap.py:1565` 的 `probe_folder_status` 走 `_connect_with_permit()`，`providers/base.py:176-183` 契约亦明示 IDLE 会话不消费 permit。STATUS 基线存 `SyncCheckpoint.cursor` 的 `last_status`/`last_probe_at`（`patrol.py:33-34,220-229`），整个已提交 diff 文件清单中无 alembic/迁移新文件。IDLE 只发信号：`idle_watcher.py:438-448` 仅以既有去重键入队 `SYNC_FOLDER_DELTA`，两新模块 grep 无 `messages`/`message_bodies` 写入。paused 一致跳过：巡检 `patrol.py:116` 与 IDLE 候选 `idle_watcher.py:282` 均以 `sync_status != PAUSED` 过滤。持有 IDLE 的账号跳过收件箱轮询：`worker/main.py:210-213` 的 held 集合跳过 + `worker/main.py:273-276` 接线，watcher 启停隔离在 `worker/main.py:517-525,567-571`、巡检 sweep 为独立失败域。

## 结论

- f001–f006 六条 finding 在已提交字节中逐条复核全部已消除，锚点与 Round 5 记录一致，收尾改动未使任一修复回退。
- 用户拍板的设计在已提交代码中成立：IDLE 独立配额（默认 32、热账号优先 + 滞回）与 8 个任务槽位两池分离、STATUS 基线复用 cursor JSONB 且无新迁移、IDLE 只入队既有 delta 不直写邮件数据、paused 双入口一致跳过、held 账号跳过收件箱轮询。
- 已提交的累积文档与代码一致：`docs/specs/mail_sync_and_storage.md` 新增 t061 契约节（独立配额 32、`cursor.last_status`、变化入队 `priority=75` 与 `patrol.py:241` 相符）、`docs/blueprint/architecture.md` 新增 t061 节（信号与拉取分离、`worker:idle_state` 状态面与 `idle_watcher.py:38` 相符）、归档目录内 task `spec.md` 的未知契约清单四项 spike 结论均已回填为已核实/已实证（扩展 `imaplib.Commands` 注册 IDLE + 专属读线程 + 控制线程唯一写者，与 `providers/imap.py:46-52,99-110` 实现相符；STATUS 缺失维度按 `None` 只比双方有值维度，与 `patrol.py:64-77` 相符；Graph 计数探测与 `providers/graph.py` 的 `probe_folder_status` 相符）。
- 总体判断：已提交的单一执行 commit 与前五轮最终 PASS 的代码形态一致，收尾文档/handoff 改动未引入代码或文档不一致，无阻断项，可放行。

verdict: PASS
