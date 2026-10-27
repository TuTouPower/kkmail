# Task review t061（reviewer_focus: 测试）

- task：`t061_idle_inbox_and_all_folder_status_patrol`
- spec：`docs/tasks/t061_idle_inbox_and_all_folder_status_patrol/spec.md`
- diff_anchor：`327acc0250f26c71d7ad2b777e876b92ff79c484`
- target：`git -C '/home/hatch/workspace/kkmail_t061' diff 327acc0250f26c71d7ad2b777e876b92ff79c484`
- round：1
- reviewed_at：2026-10-28T04:56:20+08:00

reviewed_scope: 914854af72442071

## Findings

### t061_test_f001 - AC-013「最久未探测优先」无判别力断言，计数断言与顺序无关

- 严重度：minor
- 锚点：AC-013（单轮上限与轮转已覆盖；「按最久未探测优先」子句未被断言判别）
- 位置：`tests/mail_core/test_t061_status_patrol.py:283` `test_ac013_rotation_respects_cap_and_oldest_first`，关键行 322-324
- 问题：测试注释声称「The two least-recently probed folders were chosen」，但断言只有 `result.probed == 2` 与 `len(set(provider.probed)) == 2`，从未断言被探测文件夹的身份/顺序。经核对种子数据（5 个文件夹 last_probe 依次相差 100s、均已到期）与 patrol 的 not-due 过滤（巡检后 interval 内不再到期），三轮计数 2/2/1 对「最旧优先」与「最新优先」两种实现完全相同——把 `patrol.py:138` 的升序排序反转，本测试仍全绿。`_FakeProbeProvider.probed` 已记录 remote_id，补断言成本极低。
- 建议：第一轮后断言 `provider.probed` 恰为两个最旧文件夹的 remote_id 集合；三轮后断言 5 个 remote_id 全覆盖且无重复。

### t061_test_f002 - AC-003 管理器级「断线后重连并恢复 IDLE」无端到端测试

- 严重度：minor
- 锚点：AC-003（退避数学与掉线检测已覆盖；恢复路径未覆盖）
- 位置：`tests/mail_core/test_t061_idle_watcher.py:92`（纯 backoff）、`:286` `test_ac007_repeated_failures_degrade_without_poisoning_account`；provider 层 `tests/mail_core/test_t061_imap_idle_probe.py:200` `test_idle_session_drop_detected`
- 问题：现有覆盖三段分离：backoff_delay 纯函数精确值、fake 服务器掉线被 provider 检出、factory 恒失败时 manager 只断言状态落入 backoff/fallback。没有任何用例让 session 先抛 `IdleSessionDisconnected`（或 factory 先失败 N 次）后成功重建，并断言 manager 回到 held/idling。多账号同时断线时重连打散也只有纯函数层面的 jitter 分数注入验证，manager 层无验证。
- 建议：加一个 DB 用例：factory 首次返回会抛断线异常的 fake session、第二次返回正常 fake，断言最终 `held_account_ids() == {acc}` 且状态回到 idling。

### t061_test_f003 - AC-005「持 IDLE 账号跳过收件箱轮询」与「不占任务槽位」无测试

- 严重度：minor
- 锚点：AC-005（配额与热账号优先已由 DB 用例覆盖；轮询跳过与槽位隔离两子句零测试）
- 位置：`src/mail_core/worker/main.py` `schedule_periodic_inbox_sync(..., idle_held_account_ids=...)`（diff 新增参数）；全仓 `grep idle_held_account_ids tests/` 无命中
- 问题：t061 对既有 t057 调度函数新增了 held 账号跳过逻辑，但没有任何测试调用该参数验证 held 账号不产生 inbox delta、让位后恢复轮询。同样，IDLE 会话不消费 connection_slots 仅靠 `ImapProvider.open_idle_session` 直连 `_connect()` 的构造保证（`src/mail_core/providers/imap.py:1577` 起），无测试锁定：probe 测试构造 provider 时 `permit_factory=None`，permit 交互从未被行使。
- 建议：给 `schedule_periodic_inbox_sync` 加一个 held 集合命中的单测（可仿 test_worker_scheduler 既有模式）；provider 层可用计数型 permit_factory 断言 `open_idle_session` 后 permit 获取次数为 0、而 `probe_folder_status` 为 1。

### t061_test_f004 - AC-006 仅测 sync_enabled 关闭一支，凭据指纹变更/paused/恢复分支未测

- 严重度：minor
- 锚点：AC-006（禁用分支已覆盖，其余触发与恢复未覆盖）
- 位置：`tests/mail_core/test_t061_idle_watcher.py:259` `test_ac006_disabled_account_session_closed`（唯一用例）
- 问题：生产侧关闭逻辑有三条不同分支：候选消失（禁用/paused/基线丢失）、`_reconcile_once` 的指纹不一致关闭（`src/mail_core/sync/idle_watcher.py:222-230`）、条件恢复后 `_open_watch` 重建。测试只覆盖禁用一支；凭据变更（指纹变化）与收件箱 paused、以及恢复后自动重建均无用例。`_seed_idle_account` 已支持 `paused=`/`baseline=` 参数但 watcher 测试从未使用。
- 建议：补三个小用例：改 credential_ref 后旧 session 被 close 且新 session 建立；folder 置 paused 后 session 关闭；禁用再启用后 session 自动恢复。

### t061_test_f005 - AC-015 的 IDLE 开关关闭与 AC-007 的 worker 级隔离无测试

- 严重度：minor
- 锚点：AC-015 / AC-007（巡检开关关闭已测；IDLE 开关关闭与 watcher 启动失败不拖垮 worker 未测）
- 位置：`tests/mail_core/test_t061_idle_watcher.py:176` `_manager()` 恒以 `enabled=True` 构造；`tests/mail_core/test_t061_status_patrol.py:375` `test_patrol_disabled_is_noop` 只有巡检侧对应物
- 问题：`IdleWatcherManager.start()` 在 `enabled=False` 时直接返回（`idle_watcher.py:156`），但无测试断言关闭时不建任何 session/线程；worker `run()` 中 watcher 启动异常被吞并继续主循环的隔离（`src/mail_core/worker/main.py` diff）也无测试。AC-015 要求两开关都关闭时行为与 t057 现状完全一致，目前只有巡检半边有 noop 证据，IDLE 半边靠 config 默认值/覆盖测试间接支撑。
- 建议：加 `enabled=False` 的 manager noop 用例（factory 记录调用次数为 0）；worker 级隔离可留给既有 worker 测试文件补一例或以代码审查覆盖，二选一即可。

### t061_test_f006 - AC-008/010 的 provider 适配层（Graph/Memory probe、默认 factory）无测试

- 严重度：minor
- 锚点：AC-008 / AC-010（巡检调度逻辑已由注入 fake provider 覆盖；真实适配层未触达）
- 位置：`src/mail_core/providers/graph.py` `probe_folder_status`（diff 新增）、`src/mail_core/providers/stub_memory.py` `probe_folder_status`（diff 新增）；`src/mail_core/sync/patrol.py:79` `_default_provider_factory`
- 问题：巡检 DB 用例全部经 `provider_factory=lambda account: provider` 注入 `_FakeProbeProvider`，生产默认 factory 路径从未被行使；Graph 的 `totalItemCount`/`unreadItemCount` 解析（spec 上下文区已核实 Graph 纳入巡检）与 MemoryProvider 的 probe 实现没有任何用例。另外巡检用例种子文件夹 role 恒为 `sent`，草稿/垃圾箱/自定义文件夹仅靠查询的 role 无关性间接成立，未参数化验证。
- 建议：给 GraphProvider.probe_folder_status 加一个假传输层单测（仿其既有测试模式）断言 FolderStatus 字段映射；巡检种子 role 参数化为 sent/drafts/trash/custom 各一例即可。

## 危险模式扫描（逐条调查结论）

- 恒真断言 / 纯存在性断言：未命中。全部断言落在具体值、DB 行（WorkerJob 的 dedupe_key/job_type/status/payload 精确比对）、checkpoint cursor 内容与 provider 记录上。
- 删/反转/注释断言、改测：未命中。本 diff 对既有测试零修改，只有 4 个新增测试文件，无「迁就实现」的改测。
- 跳过：命中但调查后放行。`tests/mail_core/test_t061_idle_watcher.py:190` 与 `test_t061_status_patrol.py` 的 DB 用例以 `pytest.mark.skipif(not os.environ.get("MAIL_CORE_DATABASE_URL"))` 门控，与仓库既有惯例一致（`tests/mail_core/test_worker_scheduler.py:18-19` 同款），且 conftest 有 CI 守卫 `MAIL_CORE_REQUIRE_DB=1` 时缺 URL 直接报错，非静默掩盖。本机无 PG/Docker，reviewer 实跑结果 19 passed / 12 skipped，12 个 skip 全部为此门控（见结论披露）。
- 静默错误：命中一处、调查后放行。`tests/mail_core/test_t061_imap_idle_probe.py:30` 的 `# type: ignore[attr-defined]` 仅作用于 fake 服务器 handler 读取 `self.server` 的类型标注，不抑制任何断言或运行时失败，unit 运行不以类型检查为门禁，不构成掩盖。
- mock 误用：未命中。manager 测试的 `_FakeSession` 与巡检的 `_FakeProbeProvider` 都经生产代码预留的 factory 注入点替换系统边界（provider 会话/探测），被测的 reconcile、配额选择、退避、变化判定、入队逻辑均为真实生产代码且断言落在真实 DB 行上；provider 层测试更进一步走真实 socket 的 fake IMAP 服务器与真实 `ImapProvider`。
- 阈值掩盖 / 条件跳过弱化断言：未命中。manager 测试的 `_wait_until` 超时即 assert 失败（5s 严于 AC-002 的 10s 预算）；`test_ac001_ac002_wake_enqueues_delta` 中 `snapshot in ("idling", "changed")` 的析取断言源于异步状态切换竞态，核心证据（delta job 入队）为严格断言，不构成弱化。

## AC 复验方式

- AC-001：re_verified — 实跑 `test_t061_imap_idle_probe.py` 全绿（能力门控 `test_idle_not_supported_without_capability`、SELECT 收件箱后 push/stop/timeout/掉线均走真实 ImapProvider + 真实 socket fake 服务器）；manager 资格逻辑查证 `_load_candidates` 的 sync_enabled/provider/role/paused/full_scan_complete 过滤与 DB 用例断言（DB 用例本环境 skip，未执行）。
- AC-002：re_verified — 独立实跑 `.scratch/blackbox_t061.py`：IDLE 唤醒 outcome='changed'、耗时 0.20s（AC 预算 10s 内）；入队断言查证 `test_ac001_ac002_wake_enqueues_delta`（dedupe_key 与 job_type 精确断言，DB 用例本环境 skip）；「落库」半段依赖既有 delta 管线（本 diff 外，既有测试覆盖），t061 测试只验入队，已如实标注。
- AC-003：re_verified（部分）— 纯 backoff 精确值实跑通过、provider 掉线检测实跑通过；manager 级恢复路径无判别性测试，见 f002。
- AC-004：re_verified — 直接 grep 查证 `src/mail_core/sync/idle_watcher.py` 与 `patrol.py`：只有 `enqueue_job`（SYNC_FOLDER_DELTA、既有 dedupe_key）、checkpoint cursor 与 AppSetting 状态写入，无任何 Message/message_bodies 写入；入队用例的 payload/dedupe 断言与之吻合。
- AC-005：re_verified（部分）— 配额与最热两账号由 `test_ac005_quota_limits_sessions` 断言（DB 用例本环境 skip，断言已查证）、滞回由纯函数三用例实跑通过；轮询跳过与槽位隔离无测试，见 f003。
- AC-006：re_verified（部分）— 禁用分支 DB 用例断言已查证（session close + held 清空）；指纹/paused/恢复分支未测，见 f004。
- AC-007：re_verified — `test_ac007...` 与 `test_ac001_no_idle_capability...` 断言账号不被标 failed、状态落入 backoff/fallback（DB 用例本环境 skip，断言已查证）；worker run() 的启动隔离经代码查证（try/except 包裹且主循环在 finally 外继续），无专门测试，见 f005。
- AC-008：re_verified — 巡检查询查证覆盖全部 sync_enabled 账号的非 paused、非 inbox 文件夹（收件箱归 t057，符合 spec 范围区「探测巡检覆盖其余文件夹」）；DB 用例断言已查证，role 多样性未参数化，见 f006。
- AC-009：re_verified — 纯 `changed_dimensions` 用例实跑通过（全维度/缺 UIDNEXT 回退/单侧有值不触发）；`test_ac009_unchanged_probe_enqueues_nothing` 与首探记录基线用例断言零 job（DB 用例本环境 skip）。
- AC-010：re_verified — `test_ac010_changed_probe_enqueues_delta_and_updates_baseline` 断言 job 类型/状态/payload 与基线更新（DB 用例本环境 skip，断言已查证）；入队后经既有管线落库同 AC-002 说明。
- AC-011：re_verified — `test_ac011_ac012...` 断言 paused 与 disabled 目标从未到达 provider（`provider.probed` 计数）且零 job（DB 用例本环境 skip）；\Noselect/远端消失在本仓以 sync_status=paused 表示（p060 规则），同一排除路径。
- AC-012：re_verified — 同上用例断言无基线文件夹只记录 last_status、full_scan_complete 保持 False、零 job（DB 用例本环境 skip，断言已查证）。
- AC-013：re_verified（部分）— 单轮上限与跨轮轮转计数实证已查证；最久未探测优先的顺序无判别断言，见 f001；周期内错峰由 last_probe_at + interval 到期过滤实现，逻辑经代码查证。
- AC-014：re_verified — `test_ac014_probe_failure_isolated_per_folder` 断言 failed/changed 计数、好文件夹照常入队、坏账号不标 failed（DB 用例本环境 skip，断言已查证）；失败文件夹后续周期重探无专门用例（到期逻辑与正常文件夹同一路径）。
- AC-015：re_verified — config 默认值/env 覆盖/非法值拒绝三用例实跑通过；巡检 disabled noop 断言已查证；IDLE disabled noop 未测，见 f005。
- AC-016：trust_prior — [deploy] 项，依赖实施侧本地替代证据 `.scratch/blackbox_t061.py`；reviewer 已独立重跑该脚本，结果 PASS（IDLE 唤醒 0.20s、STATUS 变化维度判定正确、无变化零判定），但真实服务商 + 第二客户端的部署实测仍未发生，不以本地替代冒充部署验证。

coverage = 15 / 16

披露：9 条 AC（002/005/006/007/008/009/010/011/012/013/014 中的 DB 集成部分）的 DB 用例在本机因无 PostgreSQL/Docker 全部 skip、未执行，上述 re_verified 基于断言逐条查证 + 可实跑的纯逻辑/provider 层用例 + 独立重跑 blackbox；建议合并前在 CI 以 `MAIL_CORE_REQUIRE_DB=1` 跑全量，确认这 12 个 DB 用例真实通过。

## 结论

- 改测方向复核：无（本 diff 未修改任何既有测试，仅新增 4 个测试文件）。
- 本轮新发现：6 条，全部 minor（critical 0 / important 0 / minor 6）。
- 未进表的提示：全量回归零新增失败已经 reviewer 独立复核——`.scratch/final_failures.txt` 的 20 条中，14 条与 base 基线文件同名，另 6 条（test_accounts_api_unit 1 条、test_archive_adoption_p15 2 条、test_gmail_sync_strategy_and_timeout 3 条）已在 /tmp 的 pristine anchor 克隆上逐条重跑，全部在 base 同样失败，确认零新增。t061 新增测试实跑 19 passed / 12 skipped（skip 均为 DB 环境门控）。
- 总体判断：测试可信度过关——mock 均在系统边界、断言落在用户可观察的 DB 行与真实协议交互上、无恒真/弱化/掩盖模式；剩余问题均为子句级覆盖缺口（f001–f006），不阻断。
- 系统性 follow-up：无（DB 用例 skip 为仓库既有惯例且有 CI 守卫，不另立项）。

verdict: PASS

## Round 2 (2026-10-28T05:03:05+08:00)

- task：`t061_idle_inbox_and_all_folder_status_patrol`
- diff_anchor：`327acc0250f26c71d7ad2b777e876b92ff79c484`
- round：2

reviewed_scope: af5318521a345e7a

### 前轮 finding 复核（t061_test_f001–f006，逐条以测试断言本身为准）

- f001（AC-013 轮转无身份/顺序断言）——**已消除**。`tests/mail_core/test_t061_status_patrol.py:294` `test_ac013_rotation_respects_cap_and_oldest_first` 现断言三轮各自的精确集合：首轮 `set(provider.probed) == {remote_ids[0], remote_ids[1]}`（:333）、次轮 `set(provider.probed[2:]) == {remote_ids[2], remote_ids[3]}`、末轮 `provider.probed[-1] == remote_ids[4]` 且 `sorted(provider.probed) == sorted(remote_ids)`（全覆盖无重复）。已对照生产排序核对判别力：种子 5 文件夹 last_probe 相差 100s 且均超 `max_unprobed_s=2400` 同属 critical 组，`patrol.py` `_rotation_key` 按 last_epoch 升序，反转排序首轮将选中最新的两个，集合断言必红，非恒真。新增回归 `test_ac013_ac014_failing_folders_do_not_starve_others`（:411）：3 个全失败文件夹、cap=2，断言第二轮 `failing.probed[-1] not in first_pair` 且全集覆盖，判别「失败集垄断每轮」的饿死场景。AC-014 尝试时钟亦已补强：`test_ac014_probe_failure_isolated_per_folder` 断言失败文件夹 `last_probe_at == now.timestamp()` 精确值、`last_probe_failures == 1`，且 +60s 立即重扫时 `result2.failed == 0`、`bad_provider.probed == []`。以上均为 DB 门控用例，本机 skip、断言逐条查证（见结论披露）。
- f002（AC-003 管理器级断线恢复无端到端测试）——**已消除**。新增 `tests/mail_core/test_t061_idle_watcher.py:331` `test_ac003_manager_recovers_after_disconnect`：factory 首建 `_DropOnceSession`（`wait_for_change` 恒抛 `IdleSessionDisconnected`）、后建正常 `_FakeSession`，断言 `len(built) >= 2`（重建发生）、`held_account_ids() == {acc_id}`、终态 `snapshot()[acc_id] == "idling"`。已核对状态机判别力：backoff 态不在 `_LIVE_STATES`，held 恢复当且仅当新会话进入 idling，snapshot 严格等值在此路径稳定（恢复后 fake 默认 outcome 为 timeout 循环、状态保持 idling），非析取弱化。多账号同时断线的打散仍仅纯函数 jitter 层覆盖——Round 1 原文即将其列为次要观察，不属本条未消除项。DB 门控、本机 skip、断言查证。
- f003（AC-005 轮询跳过与槽位隔离无测试）——**已消除**。轮询跳过：新增 `test_ac005_held_accounts_skip_inbox_polling`（`test_t061_idle_watcher.py:439`），直调生产 `schedule_periodic_inbox_sync(..., idle_held_account_ids={acc_id})` 断言 `enqueued == 0`，空 held 集合同种子断言 `enqueued == 1` 且 dedupe_key 精确命中的 job 存在——让位恢复一支同用例覆盖，计数为精确等值。槽位隔离：新增纯测试 `test_idle_session_uses_no_task_slot_but_probe_does`（`test_t061_imap_idle_probe.py:237`），计数型 permit_factory + 真实 fake IMAP 服务器 + 真实 `ImapProvider`，断言 `open_idle_session` 后 `permits.acquired == 0`、`probe_folder_status` 后 `== 1`，本轮已实跑通过（非 skip）。两子句均闭合。
- f004（AC-006 仅测禁用一支）——**已消除**。新增 `test_ac006_credential_change_rebuilds_session`（`test_t061_idle_watcher.py:365`）：改 `credential_ref` 后断言 `len(built) >= 2`、旧 session `built[0].closed is True`、held 恢复；新增 `test_ac006_paused_inbox_closes_session_and_disable_recovers`（:399）：folder 置 paused 后断言 held 清空且 `fake.closed is True`，随后禁用→再启用断言 session 自动恢复 held。三分支（指纹变更 / paused / 恢复）全覆盖，断言均为精确状态而非存在性。注记：paused 用例恢复路径与禁用切换合并在同一用例、且 factory 复用同一 fake 对象（closed 后仍可 wait），不削弱 held 集合与 closed 标志的判别力。DB 门控、本机 skip、断言查证。
- f005（AC-015 IDLE 开关关闭与 AC-007 worker 级隔离无测试）——**已消除（主项）；worker 子项按 Round 1 允许的代码审查路径闭合**。新增纯测试 `test_disabled_manager_is_noop`（`test_t061_idle_watcher.py:307`，本轮实跑通过）：`enabled=False` 的 manager 以「被调用即抛 AssertionError」的 session factory 构造，`start()` 后断言 `held_account_ids() == set()`、`snapshot() == {}`、session factory 调用记录 `calls == []`——三重精确断言，无恒真。worker 级隔离仍无专门测试，但 Round 1 本条建议明示「补一例或以代码审查覆盖，二选一即可」；本轮已复核 `src/mail_core/worker/main.py:517-525`：watcher 构造与 `start()` 在 try/except 内、异常 `log.exception` 后主循环继续（巡检/轮询为权威），隔离成立，故本条按已消除计，残留仅在结论提示。
- f006（AC-008/010 provider 适配层与默认 factory 无测试、role 未参数化）——**部分消除，残留转 f007**。已消除部分：(1) 新增 `tests/mail_core/test_t061_graph_probe.py`（3 例，本轮实跑通过）：经 GraphProvider 既有可注入 transport 边界（与 `test_gmail_graph_contracts.py` 同模式、走生产 `_call` 路径）断言 `probe_folder_status("folder-1") == FolderStatus(messages=42, uidnext=None, unseen=7, highestmodseq=None)` 精确等值、缺失计数为 None 而非 0、非 dict 应答返回 None；transport 内同时断言 method/path。(2) role 参数化已落实：`test_ac008_ac009_first_probe_records_baseline_without_enqueue`（`test_t061_status_patrol.py:151`）种子覆盖 sent/drafts/trash/custom 四种 role，断言 `result.probed == 4` 且 probed remote_id 集合与四种子精确相等、逐文件夹零 job 且基线落盘。未消除部分：`MemoryProvider.probe_folder_status` 与巡检 `_default_provider_factory` 仍零测试，见 f007。

### 本轮新发现

### t061_test_f007 - f006 残留：MemoryProvider probe 与巡检默认 factory 路径仍无测试

- 严重度：minor
- 锚点：AC-008 / AC-010（巡检调度逻辑与 Graph/IMAP 适配层已覆盖；stub 账号的真实适配路径未触达）
- 位置：`src/mail_core/providers/stub_memory.py:248` `MemoryProvider.probe_folder_status`；`src/mail_core/sync/patrol.py:80` `_default_provider_factory`
- 问题：全仓 grep 确认 `probe_folder_status` 在测试中仅命中 t061 的 IMAP/Graph/巡检 fake 三处，`tests/mail_core/test_stub_memory_provider.py` 对 probe 零用例；巡检全部 DB 用例仍以 `provider_factory=lambda account: provider` 注入 fake，生产默认 factory 从未被行使。而默认 factory 经 `build_provider` 对 `provider="stub"/"memory"` 账号恰好返回 MemoryProvider（`src/mail_core/providers/factory.py:205-206`），即巡检种子账号在生产路径下真正会用的适配器正是未测的这个：其未读计数（`is_read is False`）、modseq 的 `int(...) or None` 归一、未知文件夹返回 None（巡检按失败探测处理）任一写错都无测试拦截。影响面限于 stub 账号与测试夹具环境（生产账号为 IMAP/Graph，两者适配层均已覆盖），故 minor 不阻断。
- 建议：仿 graph probe 文件给 MemoryProvider 加 2–3 例纯单测（已知/未知文件夹、未读计数、modseq 为 0 时为 None）；默认 factory 可加一例以 stub 账号不注入 factory 跑一轮巡检，或在 factory 层断言 stub 账号返回带 probe 的 MemoryProvider，二选一即可。

### 危险模式扫描（本轮增量，逐条调查结论）

- 恒真/弱化断言：未命中。新增断言均为精确等值/精确集合/精确计数（AC-013 三轮 remote_id 集合、AC-014 时钟 `== now.timestamp()` 与重扫 `probed == []`、permit 计数 0/1、Graph FolderStatus 全字段等值）；`len(built) >= 2` 出现在「至少重建一次」的语义位置且与 closed/held 精确断言成组，不构成弱化。
- 删/反转/注释断言、迁就实现的改测：未命中。本轮对既有 t061 测试的修改全部为加强方向——AC-013 计数断言升级为身份集合断言、AC-014 追加时钟与重扫断言、AC-008 用例扩展 role 覆盖；无一处把预期改小或改向当前实现输出。生产侧随之新增「失败也推进尝试时钟」语义（`patrol.py` `_record_attempt`），由新增饿死回归用例正向锁定，属规格内行为（AC-013 未探测上限 / AC-014 失败隔离）而非测试迁就。
- 跳过：命中但放行，理由同 Round 1——新增 manager/patrol 用例沿用 `MAIL_CORE_DATABASE_URL` 门控（仓库惯例 + CI `MAIL_CORE_REQUIRE_DB=1` 守卫）；本轮实跑 24 passed / 17 skipped，17 个 skip 全部为该门控。
- 静默错误：未新增。`test_disabled_manager_is_noop` 中两处 `# pragma: no cover - must not run` 标注在「被调用即失败」的替身函数上，调用与否由 `calls == []` 与 AssertionError 双重锁定，不抑制任何断言。

## AC 复验方式（Round 2）

- AC-001：re_verified — provider 层用例本轮实跑全绿（能力门控/SELECT 收件箱/push/stop/timeout/掉线，走真实 ImapProvider + socket fake 服务器）；manager 资格过滤同 Round 1 查证，断言未变。
- AC-002：re_verified — `test_ac001_ac002_wake_enqueues_delta` 断言未变（DB 门控 skip）；Round 1 独立重跑 blackbox 唤醒 0.20s 的证据仍对应当前未改动的唤醒路径。
- AC-003：re_verified — backoff 纯函数与 provider 掉线检测本轮实跑通过；新增 manager 级恢复用例断言逐条查证（f002 已消除），DB 门控未执行。
- AC-004：re_verified — 同 Round 1 grep 查证结论未变：两条新路径只有 enqueue/checkpoint/AppSetting 写入，无 messages/message_bodies 直写。
- AC-005：re_verified — 配额/滞回用例实跑与查证同 Round 1；本轮新增轮询跳过 DB 用例断言查证 + 槽位隔离纯测试实跑通过（f003 已消除）。
- AC-006：re_verified — 禁用分支同 Round 1；新增指纹变更与 paused/恢复两用例断言逐条查证（f004 已消除），DB 门控未执行。
- AC-007：re_verified — 反复失败降级用例断言查证同 Round 1；worker 启动隔离本轮经 `worker/main.py:517-525` 代码复核闭合（f005）。
- AC-008：re_verified — 巡检覆盖查询查证同 Round 1；role 四族参数化已落实并查证断言（f006 已消除部分）；stub 账号真实适配路径残留见 f007。
- AC-009：re_verified — 纯 `changed_dimensions` 用例本轮实跑通过；无变化零入队 DB 用例断言未变。
- AC-010：re_verified — 变化入队 + 基线更新 DB 用例断言未变；Graph 适配层字段映射本轮实跑通过。
- AC-011：re_verified — paused/disabled 排除 DB 用例断言未变；新增 paused 收件箱在 IDLE 侧的关闭断言（f004 用例）同向加强。
- AC-012：re_verified — 同 Round 1：无基线只记录 last_status、零 job 的 DB 用例断言未变。
- AC-013：re_verified — 单轮上限 + 最久优先精确集合断言 + 失败集饿死回归，本轮逐条查证并核对生产排序判别力（f001 已消除）；DB 门控未执行。
- AC-014：re_verified — 失败隔离 DB 用例断言未变并新增尝试时钟精确断言与立即重扫不重探断言（查证）；失败文件夹后续周期重探由尝试时钟 + 到期逻辑同路径成立。
- AC-015：re_verified — config 三用例与巡检 disabled noop 同 Round 1；新增 IDLE disabled manager noop 纯测试本轮实跑通过（f005 已消除）。
- AC-016：trust_prior — [deploy] 项，同 Round 1：依赖实施侧本地替代证据（blackbox 已于 Round 1 独立重跑 PASS），真实服务商 + 第二客户端部署实测仍未发生。

coverage = 15 / 16

披露：t061 测试本轮独立复跑结果 `24 passed, 17 skipped`（`KKMAIL_TEST_MODE=unit .venv/bin/python -m pytest` 五个 t061 测试文件），与实施方声称一致；17 个 skip 全部为 `MAIL_CORE_DATABASE_URL` 未设置门控。本轮新消除的 f001/f002/f004 与 f003 的轮询跳过子项均为 DB 门控用例，本机未执行，其「已消除」结论基于断言逐条查证 + 生产代码判别力核对；f003 槽位隔离、f005 开关 noop、f006 Graph 三例为纯测试，已实跑通过。建议合并前在 CI 以 `MAIL_CORE_REQUIRE_DB=1` 跑全量，确认 17 个 DB 用例真实通过。

## 结论（Round 2）

- 前轮 finding 复核：f001 已消除；f002 已消除；f003 已消除；f004 已消除；f005 已消除（主项实跑验证，worker 子项按 Round 1 允许的代码审查路径复核闭合）；f006 部分消除（Graph 适配层与 role 参数化已补齐并实跑/查证，MemoryProvider probe 与默认 factory 残留转 f007）。
- 改测方向复核：无「迁就实现」的改测；本轮测试改动均为加强（身份/顺序/时钟精确断言、role 扩展、新增回归用例）。
- 本轮新发现：1 条（f007，minor，系 f006 残留的延续）。
- 未进表的提示：worker 级 IDLE 启动隔离仍无专门测试（代码复核成立，见 f005 复核）；f007 的 MemoryProvider 为 stub/测试环境适配器，生产 IMAP/Graph 路径不受影响，可随后续任一轮补齐。
- 总体判断：Round 1 的 6 条 minor 中 5 条完全消除、1 条部分消除且残留已收窄为 stub 适配层的 minor（f007）；新增/加强断言无恒真、无弱化、无换形式规避，测试可信度进一步成立，无未解决 critical / important。
- 系统性 follow-up：无。

verdict: PASS

## Round 3 (2026-10-28T05:16:17+08:00)

- task：`t061_idle_inbox_and_all_folder_status_patrol`
- diff_anchor：`327acc0250f26c71d7ad2b777e876b92ff79c484`
- round：3

reviewed_scope: cc30dc1068156a48

### 前轮 finding 复核（t061_test_f007）

- f007（MemoryProvider probe 与巡检默认 factory 零测试）——**已消除**。新增 `tests/mail_core/test_t061_memory_probe.py`（4 例，本轮实跑全过，非 DB 门控）：
  - `test_memory_probe_counts_messages_and_unread`（:35）：对含 read/unread/`is_read=None` 混合消息的文件夹断言 `probe_folder_status("Sent") == FolderStatus(messages=4, uidnext=None, unseen=2, highestmodseq=9)` 全字段精确等值——`None` 不计未读的语义被钉住，非存在性断言。
  - `test_memory_probe_zero_modseq_normalises_to_none`（:51）：`modseq=0` 时断言 `messages == 0` 且 `highestmodseq is None`，覆盖生产 `int(...) or None` 归一（`stub_memory.py:255`）。
  - `test_memory_probe_unknown_folder_returns_none`（:59）：未知文件夹精确断言 `is None`（巡检按失败探测处理、不得按无变化放行，与 spec 上下文区 STATUS 缺失契约一致）。
  - `test_default_factory_builds_memory_provider_for_stub_accounts`（:64）：以真实 `Account(provider="stub")` 对象直调生产 `_default_provider_factory`（`patrol.py:80` → `build_provider`），断言返回 `MemoryProvider` 实例且其 probe 对未播种文件夹返回 None——走的是生产 factory 路径而非注入替身，正是 f007 建议的「factory 层断言」选项。
  - 判别力已由 reviewer 独立变异实证（/tmp 副本变异、工作仓库未动）：把未读计数改为 `is_read is not True` → 用例 1 变红；去掉 modseq 的 `or None` 归一 → 用例 2 变红。两处变异均被精确断言拦截，非恒真。

### 本轮另一新增测试复核（code 侧 f003 修复的回归测试，非本报告 finding 的处置，但属本轮新增断言、按任务要求一并审）

- `test_blocked_watch_deregisters_and_retries_after_expiry`（`tests/mail_core/test_t061_idle_watcher.py:343`，纯测试、本轮实跑通过）：断言链为精确等值——首轮 reconcile 后状态 `== "fallback"` 且 factory 调用 `len(calls) == 1`；仍在 blocked 窗口内第二轮 reconcile 后 `len(calls) == 1`（不重试）；把 blocked 时间戳老化 7200s（生产 `_BLOCKED_RETRY_S = 3600.0`，`idle_watcher.py:43`，老化量 2 倍于窗口、非临界值）且 factory 转成功后第三轮 reconcile，断言 `held_account_ids() == {acc_id}`、`len(calls) == 2`、终态 `snapshot()[acc_id] == "idling"`。
- **mock 边界独立判断：`_load_candidates` 桩与 `_FakeDbSession` 不构成「mock 掉被测逻辑」**。被测对象是 reconcile 的开/关 watch 决策、`_register_blocked` 的注销、`_blocked` 的指纹+时龄咨询与过期重试这一状态机本身，全部走真实生产代码（含真实线程 `_watch_loop` 的 factory 抛 `IdleNotSupportedError` 分支）：`_reconcile_once` 内的 `select_idle_holders` 配额选择仍以桩返回的候选为输入真实运行，未被替代。桩只替代两个系统边界——候选枚举（一条 DB SELECT 查询，其真实路径由 DB 门控的种子用例覆盖）与会话持久化（`_FakeDbSession.get(Account/Folder)` 恰是 `_open_watch` 快照读取的边界，`add/commit/flush` 空实现只影响 `_publish_state` 的可观测落盘，不影响被断言的内存状态机）。老化手法是直接改写 `_blocked` 条目的时间戳，属时钟边界操纵（等价于冻结/推进 `time.monotonic`），且指纹值取自生产代码真实登记的条目——若生产从未登记 block，该行即 KeyError，不会假绿。
- 判别力已由 reviewer 独立变异实证：/tmp 副本上摘除 `_register_blocked` 中的注销（`_watches.pop`）后，该测试变红（1 failed），与实施方自证一致但不依赖其自述；变异副本已删除，工作仓库未被触碰。

### 危险模式扫描（本轮增量，逐条调查结论）

- 恒真/弱化断言：未命中。两个新文件的断言全部为精确等值/精确集合/精确计数；`isinstance(provider, MemoryProvider)` 为类型断言，但与随后的 probe 行为断言成组出现，且正是 f007 建议的 factory 层验证方式，不作 AC 的单独证据。
- 删/反转/注释断言、迁就实现的改测：未命中。本轮对既有 t061 测试零修改，仅新增 1 个测试文件与 1 个测试用例。
- 跳过：未新增。两个新文件均无 skip 门控，纯 unit 模式可跑；本轮实跑 t061 六个测试文件结果 `29 passed, 17 skipped`，17 个 skip 全部为 Round 1/2 已放行的 `MAIL_CORE_DATABASE_URL` DB 门控，与实施方声称一致。
- 静默错误：未新增。blocked 用例中的 `# noqa: SLF001` 仅标注测试接缝处对私有成员的访问，不抑制任何断言或运行时失败。
- mock 误用：未命中，理由见上节独立判断（桩位于候选枚举与会话持久化两个系统边界，被测状态机为真实生产代码，且变异实证可红）。

## AC 复验方式（Round 3）

- AC-001：re_verified — 同 Round 2（provider 层用例本轮随全量实跑通过；manager 资格过滤断言未变）。
- AC-002：re_verified — 同 Round 2（入队断言未变、DB 门控 skip；Round 1 blackbox 独立重跑证据仍对应未改动的唤醒路径）。
- AC-003：re_verified — 同 Round 2（backoff 纯函数与掉线检测本轮实跑通过；manager 级恢复用例断言未变）。
- AC-004：re_verified — 同 Round 2 grep 查证结论未变；本轮新增 blocked 回归用例进一步实证 IDLE 路径异常只走 fallback/enqueue 边界，不直写邮件表。
- AC-005：re_verified — 同 Round 2（配额/滞回/轮询跳过/槽位隔离证据未变，本轮随全量实跑/查证维持）。
- AC-006：re_verified — 同 Round 2 三分支断言未变；本轮新增 blocked 注销/过期重试回归用例（纯测试实跑 + 变异证红）补强了「blocked 后指纹不变也可在窗口过期后重试」一支。
- AC-007：re_verified — 同 Round 2（反复失败降级断言未变；worker 启动隔离经代码复核闭合）。
- AC-008：re_verified — 巡检覆盖与 role 四族断言同 Round 2；本轮 f007 消除后，stub 账号经默认 factory 的真实适配路径已由 `test_t061_memory_probe.py` 实跑锁定。
- AC-009：re_verified — 同 Round 2（纯 `changed_dimensions` 用例本轮实跑通过；无变化零入队 DB 用例断言未变）。
- AC-010：re_verified — 同 Round 2（变化入队 + 基线更新断言未变；Graph 适配层实跑通过；Memory 适配层本轮补齐实跑）。
- AC-011：re_verified — 同 Round 2（paused/disabled 排除断言未变）。
- AC-012：re_verified — 同 Round 2（无基线只记录 last_status、零 job 断言未变）。
- AC-013：re_verified — 同 Round 2（最久优先精确集合断言 + 饿死回归，断言未变）。
- AC-014：re_verified — 同 Round 2（失败隔离 + 尝试时钟精确断言未变）。
- AC-015：re_verified — 同 Round 2（config 三用例、巡检 disabled noop、IDLE disabled manager noop 本轮随全量实跑通过）。
- AC-016：trust_prior — [deploy] 项，同前轮：依赖实施侧本地替代证据（blackbox 已于 Round 1 独立重跑 PASS），真实服务商 + 第二客户端部署实测仍未发生。

coverage = 15 / 16

披露：本轮独立实跑 t061 六个测试文件为 `29 passed, 17 skipped`（`KKMAIL_TEST_MODE=unit`），skip 均为 DB 环境门控；DB 门控用例的断言与 Round 2 查证一致、本轮未改动。判别力变异实验在 /tmp 副本上完成并已清理，工作仓库除本报告追加外未被修改。trust_prior 仅 AC-016 一项（占比 6%），不触发人工抽查提示。

## 结论（Round 3）

- 前轮 finding 复核：f007 已消除（MemoryProvider probe 三例 + 默认 factory 一例，精确断言、实跑通过、变异证红）；f001–f005 的消除状态与 f006 的其余已消除部分维持 Round 2 结论，相关断言本轮未被改动。
- 改测方向复核：无「迁就实现」的改测；本轮只有新增测试，无既有断言修改。
- 本轮新发现：0 条。
- 未进表的提示：无。
- 总体判断：三轮累计 finding f001–f007 全部消除；本轮新增断言无恒真、无弱化、mock 边界正当（候选枚举/会话持久化/时钟三处边界，被测状态机为真实生产代码），且关键回归用例经 reviewer 独立变异证红。无未解决 critical / important。
- 系统性 follow-up：无。

verdict: PASS

## Round 4 (2026-10-28T05:22:41+08:00)

- task：`t061_idle_inbox_and_all_folder_status_patrol`
- diff_anchor：`327acc0250f26c71d7ad2b777e876b92ff79c484`
- round：4

reviewed_scope: 09a9b918fa3cf746

### 前轮 finding 复核（t061_test_f001–f007）

- f001–f007 的消除状态维持 Round 3 结论，无回归。本轮生产侧改动经 diff 核对仅有 code review Round 3 两条 minor 的修复——`idle_watcher.py:426-432` `_register_blocked` 身份守卫（current 存在且非本人时 early return）与 `idle_watcher.py:214-220` `_reconcile_once` 残留状态清扫（stale_ids 同时 pop `_states` 与 `_blocked`、且排除仍持 watch 的账号）——未触碰任何既有测试断言所依赖的语义；f001–f007 对应的关键用例（AC-013 精确集合断言、AC-003 manager 恢复、AC-005 轮询跳过/槽位隔离、AC-006 三分支、disabled noop、Graph/Memory probe 与默认 factory、blocked 注销/过期重试）本轮逐一抽查仍在原位、断言未变，并随本轮全量实跑维持结果（见披露）。

### 本轮新增两条测试复核（code review Round 3 f004/f005 的回归测试）

- `test_register_blocked_stale_thread_cannot_clobber_new_watch`（`tests/mail_core/test_t061_idle_watcher.py:402-440`，纯测试、本轮实跑通过）：以真实生产 `_Watch` 数据类构造 fingerprint 不同的 fresh（fp-new）与 stale（fp-old）两个实例，预置 fresh 为 `_watches[acc]` 且状态 idling；对 stale 调 `_register_blocked` 后三处断言互不替代——`_watches[acc_id] is fresh`（:433，身份而非存在性）、`_states[acc_id] == "idling"`（:434）、`acc_id not in _blocked`（:435）；随后对 fresh 本人调用，断言注销（:438）、状态落 fallback（:439）、block 落账且指纹为 fp-new（:440 `_blocked[acc_id][0] == "fp-new"`）——正反两向（陈旧者不得覆写 / 本人仍须登记）同用例闭合，无恒真、无析取弱化。判别力已由 reviewer 独立变异实证（/tmp 副本、工作仓库未动）：(A) 摘除身份守卫 early return → 红于 :434（state 被覆写为 fallback）；(B) 守卫分支只覆写 `_blocked` → 红于 :435；(C) 守卫分支只 pop `_watches` → 红于 :433；(D) `_register_blocked` 整体 no-op → 红于 :438（本人注销断言）。四组变异分别命中四条不同断言，证明三处守卫效果与本人路径各自被独立钉住。
- `test_reconcile_sweeps_blocked_state_for_departed_accounts`（`tests/mail_core/test_t061_idle_watcher.py:443-465`，纯测试、本轮实跑通过）：预置 `_states[acc]="fallback"` 与 `_blocked[acc]=("fp", monotonic())`（恰为 blocked 账号注销后的真实残留形态，其 watch 已不在 `_watches`，与生产清扫的 `- set(self._watches)` 排除条件自洽），候选集桩为空后跑一轮真实 `_reconcile_once`，断言公开面 `snapshot() == {}`（:464）与 `_blocked == {}`（:465）双双精确清空。判别力变异实证：(E) 禁用清扫（stale_ids=∅）→ 红于 :464；(F) 清扫只清 `_states` 不清 `_blocked` → 红于 :465。两条断言各自独立可红。
- **白盒 seam 正当性（reviewer 独立判断）：正当**。被测对象是 manager 内部状态机：其公开面只有 `start/stop/held_account_ids/snapshot`（`idle_watcher.py:162-195`），其中 snapshot 只能观测 `_states` 的拷贝、held 只能间接反映 `_watches` 的存在性（无法判别 watch 的对象身份，而身份正是 f004 的被测不变量）；`_blocked` 经全仓 grep 确认只在 `idle_watcher.py` 内部读写、无任何公开读口，其指纹内容除直接读外不可观测。故两测试对 `_watches/_states/_blocked` 的直接读写是触达被测不变量的唯一途径，不是「import 内部凑数」：调用的 `_register_blocked` 与 `_reconcile_once` 均为真实生产代码、同步执行、无线程竞态与 timeout 掩盖。sweep 用例的 `_load_candidates = lambda: []` 桩与 Round 3 已放行的同款 seam 一致——只替代候选枚举这一 DB 查询边界，被测的清扫/选择/开合逻辑仍全程真实运行。每处私有访问均带 `# noqa: SLF001` 就地标注（非文件级抑制、不掩盖任何断言或运行时失败），与仓库既有 t061 测试的 seam 标注惯例一致。

### 危险模式扫描（本轮增量，逐条调查结论）

- 恒真/弱化断言：未命中。两条新测试断言全为身份（`is`）、精确等值与精确成员关系；唯一未断言的量是 `_blocked` 元组的时间戳分量——其行为效果（窗口内不重试/过期重试）已由 Round 3 的 blocked 回归用例锁定，不属本用例职责。
- 删/反转/注释断言、迁就实现的改测：未命中。本轮对既有 t061 测试零修改，仅在同一文件新增两个用例（全量用例数 46 → 48，与实跑计数吻合）。
- 跳过：未新增。两条新测试均无 DB 门控、unit 模式直接执行；本轮 17 个 skip 全部为 Round 1 起已放行的 `MAIL_CORE_DATABASE_URL` 门控。
- 静默错误：未新增。`# noqa: SLF001` 为私有访问标注，理由见上节 seam 判断。
- mock 误用：未命中。sweep 用例的候选枚举桩位于 DB 查询边界（同 Round 3 结论）；stale 用例不使用任何 mock，`_Watch` 为真实生产类型、manager 为真实实例。

## AC 复验方式（Round 4）

- AC-001：re_verified — 同 Round 3（provider 层用例本轮随全量实跑通过；manager 资格过滤断言未变）。
- AC-002：re_verified — 同 Round 3（入队断言未变、DB 门控 skip；Round 1 blackbox 独立重跑证据仍对应未改动的唤醒路径）。
- AC-003：re_verified — 同 Round 3（backoff 纯函数、掉线检测、manager 级恢复用例本轮随全量实跑/查证维持）。
- AC-004：re_verified — 同 Round 3 grep 查证结论未变；本轮两处生产改动只读写 watcher 内部状态字典，不新增任何邮件表写入。
- AC-005：re_verified — 同 Round 3（配额/滞回/轮询跳过/槽位隔离证据未变）；本轮身份守卫修复不改变配额选择路径。
- AC-006：re_verified — 同 Round 3 三分支断言未变；本轮新增 stale 守卫用例（实跑 + 四组变异证红）补强「watch 被替换后陈旧线程退出不得覆写新 watch 状态与 block 记录」一支，sweep 用例补强「blocked 账号退出候选集后状态面无残留」一支。
- AC-007：re_verified — 同 Round 3（反复失败降级断言未变；worker 启动隔离经代码复核闭合）；sweep 用例同时证明 departed 账号不以残留 fallback 长期挂在状态面。
- AC-008：re_verified — 同 Round 3（巡检覆盖、role 四族、默认 factory/Memory 适配断言未变）。
- AC-009：re_verified — 同 Round 3（纯 `changed_dimensions` 用例本轮实跑通过；无变化零入队断言未变）。
- AC-010：re_verified — 同 Round 3（变化入队 + 基线更新断言未变；Graph/Memory 适配层实跑维持）。
- AC-011：re_verified — 同 Round 3（paused/disabled 排除断言未变）。
- AC-012：re_verified — 同 Round 3（无基线只记录 last_status、零 job 断言未变）。
- AC-013：re_verified — 同 Round 3（最久优先精确集合断言 + 饿死回归，断言未变）。
- AC-014：re_verified — 同 Round 3（失败隔离 + 尝试时钟精确断言未变）。
- AC-015：re_verified — 同 Round 3（config 三用例、巡检 disabled noop、IDLE disabled manager noop 本轮随全量实跑通过）；本轮清扫修复使「账号 departed 后无残留状态」同向成立。
- AC-016：trust_prior — [deploy] 项，同前轮：依赖实施侧本地替代证据（blackbox 已于 Round 1 独立重跑 PASS），真实服务商 + 第二客户端部署实测仍未发生。

coverage = 15 / 16

披露：本轮独立实跑 t061 六个测试文件为 `31 passed, 17 skipped`（`KKMAIL_TEST_MODE=unit`），与实施方声称一致；较 Round 3 的 29 passed 恰多两条本轮新增纯测试，17 个 skip 全部为 DB 环境门控、其 DB 用例断言与 Round 2/3 查证一致、本轮未改动。判别力变异实验共六组（A–F），全部在 /tmp 副本上完成、均被目标断言精确拦截，副本已删除，工作仓库除本报告追加外未被修改（git status 与评审开始时一致）。trust_prior 仅 AC-016 一项（占比 6%），不触发人工抽查提示。

## 结论（Round 4）

- 前轮 finding 复核：f001–f007 全部维持已消除，无回归、无换形式弱化。
- 改测方向复核：无「迁就实现」的改测；本轮只有新增测试，无既有断言修改。
- 本轮新发现：0 条。
- 未进表的提示：无。
- 总体判断：两条新增回归测试断言精确（身份/指纹/双清空）、正反两向闭合，白盒 seam 经独立判断正当（公开面无法观测 watch 身份与 block 记录），且六组 reviewer 变异全部证红；无未解决 critical / important。
- 系统性 follow-up：无。

verdict: PASS

## Round 5 (2026-10-28T05:25:49+08:00)

- task：`t061_idle_inbox_and_all_folder_status_patrol`
- diff_anchor：`327acc0250f26c71d7ad2b777e876b92ff79c484`
- round：5（最后一轮，review_limit=5）

reviewed_scope: adcd88696bca5dd2

### 前轮 finding 复核（t061_test_f001–f007）

- f001–f007 全部维持已消除，无回归、无换形式弱化。本轮生产侧改动经 grep 与逐行核对仅为 code review f006 的修复（`_set_state` 签名与身份守卫，见下节），未触碰 f001–f007 对应断言所依赖的任何语义；六个 t061 测试文件本轮独立实跑 `31 passed, 17 skipped`（`KKMAIL_TEST_MODE=unit`），与 Round 4 的 31 passed 一致（本轮无新增用例、仅既有用例内断言扩展），17 个 skip 全部为已放行的 `MAIL_CORE_DATABASE_URL` DB 门控。

### 本轮断言扩展复核（`test_register_blocked_stale_thread_cannot_clobber_new_watch`）

- 扩展位置：`tests/mail_core/test_t061_idle_watcher.py:436-441`，紧接 Round 4 已审的 `_register_blocked(stale)` 三断言（:433-435）之后，测的是 code review f006 新守卫的另一条生产路径——通用 `_set_state`（`src/mail_core/sync/idle_watcher.py:450-459`，`if self._watches.get(watch.account_id) is watch` 才写 `_states`）。
- 断言精确性：三步均为精确等值，无恒真、无析取、无存在性冒充。(1) `_set_state(stale, "backoff")` 后断言 `_states[acc_id] == "idling"`（:437-438）——选 "backoff" 而非任意值有判别意义：它是 `_watch_loop` 中陈旧线程真实会写的两个状态之一（:375/:406 的失败退避），且与现存 "idling" 不同，若守卫失效必被覆写可见。(2) `_set_state(fresh, "changed")` 后断言 `_states[acc_id] == "changed"`（:439-440）——正向路径精确断言，证明守卫不是「一律不写」的假守卫。(3) `_set_state(fresh, "idling")`（:441）写回，无紧随断言（见结论未进表提示）。
- 判别力（reviewer 独立变异实证，/tmp 副本、工作仓库未动，副本已删除）：(A) 守卫删除、改为无条件写 → 红于 :438（`'backoff' == 'idling'`）；(B) `_set_state` 整体 no-op → 红于 :440（`'idling' == 'changed'`），正向断言独立可红；(C) 守卫弱化为存在性检查（`account_id in _watches`，不验身份）→ 红于 :438——证明 :438 钉住的是「身份」而非「该账号有 watch 存在」，这是本次扩展最关键的区分，扩展断言恰好能判别。三组变异分别命中 :438/:440/:438 且失败值与预期一致，非偶然红。
- 正反两向闭合性：同一用例内 stale 被拒（:438）与 fresh 被放行（:440）成对出现，随后 `_register_blocked(fresh)` 的既有断言链（:443-446）不受扩展干扰、仍全绿；扩展没有删改 Round 4 的任何既有断言，只在其后追加，属加强方向。

### `_set_state` 签名变更对其他测试的影响

- 全仓 grep 核对：生产调用点共 5 处，全部已同步为新签名 `(watch, state)`——`idle_watcher.py:375`（connect 失败 backoff）、`:381`（idling）、`:389`（changed）、`:391`（changed 后写回 idling）、`:406`（session 异常 backoff），均位于 `_watch_loop(watch, ...)` 内、传入的正是该线程的真实 watch 对象，身份守卫在正常路径恒成立；测试侧调用点只有本用例的 :437/:439/:441 三处，无任何旧签名 `(account_id, state)` 残留调用。
- 间接路径不受影响：经 `_open_watch` 建立的 watch 对象即 `_watches` 中的对象本身，其线程后续所有 `_set_state` 调用身份恒等；本轮全量实跑 31 passed（含 provider 层掉线/重入、manager 恢复、blocked 重试等走真实 `_watch_loop` 的用例）即为实证。DB 门控的 17 个 skip 用例同样经 `_open_watch` 的真实对象路径，不存在「测试替身 watch 与注册 watch 非同一对象」会被新守卫误拒的构造，故签名变更对 skip 用例无隐藏影响（此点经种子/factory 构造逐一核对：manager 测试的替身只替换 session factory，不替换 watch 对象本身）。

### 危险模式扫描（本轮增量，逐条调查结论）

- 恒真/弱化断言：未命中。新增断言为精确等值（:438、:440），且经三组变异证红。
- 删/反转/注释断言、迁就实现的改测：未命中。本轮对既有测试的唯一修改是在既有用例内追加断言，原有断言逐字保留；扩展对应的生产守卫来自 code review f006 的独立修复（陈旧线程不得覆写新 watch 状态，与 `_register_blocked` 既有守卫同构），是为新生产语义补回归断言，方向合法，非把预期改向实现输出。
- 跳过/静默错误/mock 误用/阈值掩盖：均未新增。扩展沿用 Round 4 已判定正当的白盒 seam（`_watches`/`_states` 直接读写 + `# noqa: SLF001` 就地标注），理由不变：`_states` 的写路径除 snapshot 拷贝外无公开观测口能区分写入者身份。

## AC 复验方式（Round 5）

- AC-001：re_verified — 同 Round 4（provider 层用例本轮随全量实跑通过；资格过滤断言未变）。
- AC-002：re_verified — 同 Round 4（入队断言未变、DB 门控 skip；Round 1 blackbox 独立重跑证据仍对应未改动的唤醒路径）。
- AC-003：re_verified — 同 Round 4（backoff/掉线/manager 恢复证据未变）；本轮 `_set_state` 守卫不改变 backoff 数学与重连路径，5 处调用点已逐行核对。
- AC-004：re_verified — 同 Round 4 grep 查证结论未变；本轮生产改动只在 watcher 内部状态字典的写入守卫，不新增任何邮件表写入。
- AC-005：re_verified — 同 Round 4（配额/滞回/轮询跳过/槽位隔离证据未变，本轮随全量实跑维持）。
- AC-006：re_verified — 同 Round 4 三分支断言未变；本轮扩展断言（三组变异证红）进一步钉住「陈旧线程经通用状态路径亦不得覆写新 watch」一支，与 `_register_blocked` 守卫形成双路径闭合。
- AC-007：re_verified — 同 Round 4（反复失败降级断言未变；worker 启动隔离经代码复核闭合）；新守卫使陈旧线程的 backoff 写入同样被拒，降级语义不被陈旧线程污染。
- AC-008：re_verified — 同 Round 4（巡检覆盖、role 四族、默认 factory/Memory 适配断言未变）。
- AC-009：re_verified — 同 Round 4（纯 `changed_dimensions` 用例本轮实跑通过；无变化零入队断言未变）。
- AC-010：re_verified — 同 Round 4（变化入队 + 基线更新断言未变；Graph/Memory 适配层实跑维持）。
- AC-011：re_verified — 同 Round 4（paused/disabled 排除断言未变）。
- AC-012：re_verified — 同 Round 4（无基线只记录 last_status、零 job 断言未变）。
- AC-013：re_verified — 同 Round 4（最久优先精确集合断言 + 饿死回归，断言未变）。
- AC-014：re_verified — 同 Round 4（失败隔离 + 尝试时钟精确断言未变）。
- AC-015：re_verified — 同 Round 4（config 三用例、双开关 disabled noop 本轮随全量实跑通过）。
- AC-016：trust_prior — [deploy] 项，同前轮：依赖实施侧本地替代证据（blackbox 已于 Round 1 独立重跑 PASS），真实服务商 + 第二客户端部署实测仍未发生。

coverage = 15 / 16

披露：本轮独立实跑 t061 六个测试文件为 `31 passed, 17 skipped`（`KKMAIL_TEST_MODE=unit`），与实施方声称一致；判别力变异实验共三组（A–C），全部在 /tmp 副本完成、均被目标断言精确拦截，副本已删除，工作仓库除本报告追加外未被修改。trust_prior 仅 AC-016 一项（占比 6%），不触发人工抽查提示。

## 结论（Round 5）

- 前轮 finding 复核：f001–f007 全部维持已消除，无回归。
- 改测方向复核：无「迁就实现」的改测；本轮唯一测试改动为在既有用例内追加与 code review f006 生产守卫对应的回归断言，既有断言零删改。
- 本轮新发现：0 条。
- 未进表的提示：`test_t061_idle_watcher.py:441` 的写回 `_set_state(fresh, "idling")` 无紧随断言——经核查不构成覆盖缺口：fresh 正向写路径已由 :440 的 `"changed"` 精确断言独立钉住（变异 B 证红），写回调用的是同一方法、同一对象、仅参数不同；且其后 `_register_blocked(fresh)` 的断言（:444-446）由该方法自行覆写状态为 fallback，并不依赖写回是否生效，故写回仅为状态卫生、无独立可观测行为待验。不出 finding。
- 总体判断（最终结论）：五轮累计 finding f001–f007 全部消除且无回归；本轮断言扩展精确（stale 拒写 / fresh 放行成对、均为精确等值）、具判别力（三组变异分别证红，且能区分身份守卫与存在性检查），`_set_state` 签名变更的全部生产与测试调用点已同步、无隐藏受害用例。无未解决 critical / important，亦无 minor。
- 系统性 follow-up：无。

verdict: PASS

## Round 6 (2026-10-28T05:39:46+08:00)

reviewed_scope: 56fefa3627511b3d

本轮为证据修复轮：对已提交的单一执行 commit `8016faa4a95d996282ec1168e15b6ad6a02b1a57`（base 为其 first parent `327acc0250f26c71d7ad2b777e876b92ff79c484`）的实际交付字节做确认性重审，核对 Round 1–5 的 PASS 结论对已提交内容仍然成立。上方 reviewed_scope 按工具链算法对该 commit tip 计算。审阅由独立 reviewer 执行，未编辑仓库内任何文件（全量对照的 pristine base worktree 建在 /tmp 并已清理）。

### 前轮 finding 复核

- f001（AC-013 精确集合 + 失败集饿死回归 + AC-014 尝试时钟）——已消除，已提交字节确认。`tests/mail_core/test_t061_status_patrol.py:294` `test_ac013_rotation_respects_cap_and_oldest_first` 三轮精确集合断言：首轮 `set(provider.probed) == {remote_ids[0], remote_ids[1]}`（:323）、次轮 `set(provider.probed[2:]) == {remote_ids[2], remote_ids[3]}`（:336）、末轮 `provider.probed[-1] == remote_ids[4]` 且 `sorted(provider.probed) == sorted(remote_ids)`（:346-348，全覆盖无重复）；与生产 `patrol.py` `_rotation_key`（critical 组优先 + last_epoch 升序）对照有判别力，反转排序必红。饿死回归 `test_ac013_ac014_failing_folders_do_not_starve_others`（:411）：3 个全失败文件夹、cap=2，断言 `failing.probed[-1] not in first_pair` 且 `set(failing.probed) == set(remote_ids)`（:453-454）。AC-014 尝试时钟在 `test_ac014_probe_failure_isolated_per_folder`（:355）：`cp_bad.cursor["last_probe_at"] == now.timestamp()`、`last_probe_failures == 1`（:389-390），+60s 重扫 `result2.failed == 0` 且 `bad_provider.probed == []`（:404 一带）。均为 DB 门控用例，本机 skip、断言逐条查证。
- f002（管理器级断线恢复）——已消除。`tests/mail_core/test_t061_idle_watcher.py:498` `test_ac003_manager_recovers_after_disconnect`：factory 首建 `_DropOnceSession`（`wait_for_change` 恒抛 `IdleSessionDisconnected`）、后建正常 `_FakeSession`，断言 `len(built) >= 2`、`held_account_ids() == {acc_id}`、`snapshot()[acc_id] == "idling"`，精确终态非析取。DB 门控、本机 skip、断言查证。
- f003（held 跳过轮询 + permit 计数）——已消除。轮询跳过：`test_t061_idle_watcher.py:606` `test_ac005_held_accounts_skip_inbox_polling` 直调生产 `schedule_periodic_inbox_sync(..., idle_held_account_ids={acc_id})` 断言 `enqueued == 0`，空 held 集断言 `enqueued == 1` 且 dedupe_key 精确命中的 job 存在（DB 门控 skip、断言查证）。permit 计数：`test_t061_imap_idle_probe.py:237` `test_idle_session_uses_no_task_slot_but_probe_does`，计数型 permit_factory + 真实 fake IMAP 服务器 + 真实 `ImapProvider`，断言 `open_idle_session` 后 `permits.acquired == 0`、`probe_folder_status` 后 `== 1`——本轮实跑通过，非 skip。
- f004（指纹变更重建 / paused 关闭 / 禁用恢复三分支）——已消除。`test_t061_idle_watcher.py:532` `test_ac006_credential_change_rebuilds_session`：改 `credential_ref` 后断言 `len(built) >= 2`、`built[0].closed is True`、held 恢复；`:566` `test_ac006_paused_inbox_closes_session_and_disable_recovers`：paused 后 held 清空且 `fake.closed is True`，随后禁用→再启用断言 held 自动恢复。三分支齐全，DB 门控 skip、断言查证。
- f005（IDLE 开关关闭的 manager noop）——已消除，且为纯测试、本轮实跑通过。`test_t061_idle_watcher.py:474` `test_disabled_manager_is_noop`：`enabled=False`，DB session factory 被调用即抛 `AssertionError`，`start()` 后断言 `held_account_ids() == set()`、`snapshot() == {}`、idle factory 调用记录 `calls == []`，三重精确断言。
- f006（Graph probe 字段映射 3 例 + AC-008 四 role 参数化）——已消除。`tests/mail_core/test_t061_graph_probe.py` 三例（:24/:31/:38，本轮实跑通过）：经可注入 transport 走生产 `_call` 路径，断言 `probe_folder_status("folder-1") == FolderStatus(messages=42, uidnext=None, unseen=7, highestmodseq=None)` 全字段等值、缺失计数为 None 非 0、非 dict 应答返回 None，transport 内同时断言 method/path。AC-008 参数化在 `test_t061_status_patrol.py:151` `test_ac008_ac009_first_probe_records_baseline_without_enqueue`：种子覆盖 sent/drafts/trash/custom 四 role，断言 `result.probed == 4` 且 `set(provider.probed)` 与四种子 remote_id 精确相等、逐文件夹零 job（DB 门控 skip、断言查证）。
- f007（MemoryProvider probe 3 例 + 默认 factory 1 例）——已消除，纯测试、本轮实跑通过。`tests/mail_core/test_t061_memory_probe.py`：`:33` 混合 read/unread/`is_read=None` 断言 `== FolderStatus(messages=4, uidnext=None, unseen=2, highestmodseq=9)` 全字段等值；`:50` modseq=0 归一为 None；`:58` 未知文件夹 `is None`；`:63` 以真实 `Account(provider="stub")` 直调生产 `_default_provider_factory`，断言返回 `MemoryProvider` 实例且 probe 行为符合预期——走生产 factory 路径，非注入替身。

### 实跑结果

- t061 六文件（`KKMAIL_TEST_MODE=unit .venv/bin/python -m pytest <六文件> -q`，worktree 内，已提交 HEAD `8016faa4`）：**31 passed / 17 skipped**，与预期口径完全一致。`-rs` 复核 17 个 skip 全部为 `MAIL_CORE_DATABASE_URL not set`（idle_watcher 9 个 + status_patrol 8 个），无其他 skip 原因。
- 全量对照（口径 `pytest tests/mail_core -q`，两边均实跑）：HEAD 侧 **1358 passed / 20 failed / 300 skipped**（同命令复跑两次，失败集一致）；/tmp pristine base worktree（`327acc02`，借用主 worktree `.venv`）**1327 passed / 20 failed / 283 skipped**。失败集经 `sort` + `diff` 比对**逐条一致（20 条完全相同，FAILED_SETS_IDENTICAL）**，零新增；HEAD 相对 base 的增量恰为 +31 passed / +17 skipped，与 t061 六文件的 48 个用例精确吻合。对照 worktree 已 `worktree remove --force` 清理。
- 绝对数与 handoff 声称（1508 passed / 20 failed / 305 skipped）的偏差已查明、非测试弱化：`pytest tests --collect-only` 为 1833 个用例，恰等于 1508+20+305，即声称口径为 `tests/` 全量（含 `tests/scripts` 等 mail_core 之外的 155 个用例：150 passed + 5 skipped）；本轮按任务指定口径只跑 `tests/mail_core`（1678 个用例），故绝对数低 150/5，但同口径下 HEAD 与 base 的失败集逐条一致这一核心结论不受影响。

### 已提交测试文件审查

- 断言精确性：f001–f007 对应用例均为等值 / 精确集合 / 精确计数断言，未见以宽松包含冒充的判别断言；仅存的两处析取（`snapshot in ("idling", "changed")`、降级用例的 `in ("backoff", "fallback")`）均为前轮已审查放行的异步竞态/降级语义，非本轮 finding 对应路径。
- 就地改测迁就实现：未命中。`git diff --name-status 327acc02 8016faa4 -- tests/` 显示六个 t061 测试文件全部为新增（A），对任何既有测试文件零修改，不存在把旧预期改成实现输出的情况；worktree 与已提交字节在 `tests/`、`src/` 上 `git diff HEAD` 为空，审阅对象与 commit 一致。
- mock 边界：未发现 mock 掉被测逻辑。`_FakeSession` / `_FakeProbeProvider` 经生产预留的 factory 注入点替换会话/探测边界，被测的 reconcile、配额选择、退避、变化判定、轮转与入队逻辑均为真实生产代码；Graph probe 走生产 `_call` + 可注入 transport（与仓库既有 Graph 测试同模式），IMAP permit 与 Memory probe 用例走真实 provider 实现。

### 本轮新发现

无（0 条）。

## 结论

- test 路 7 条 finding（f001–f007）的修复全部存在于已提交 commit `8016faa4` 的测试字节中，锚点与处置表逐条对齐，无收尾改动导致的丢失或换形式弱化。
- t061 六文件实跑 31 passed / 17 skipped，skip 全为 DB 环境门控，与预期口径一致。
- 全量对照（同口径 `tests/mail_core`）HEAD 与 base 失败集逐条一致、零新增，增量恰为 t061 的 48 个用例；handoff 绝对数偏差系 `tests/` 与 `tests/mail_core` 的口径差，已算术对平。
- 已提交测试无恒真/弱化断言、无就地改测、无 mock 掉被测逻辑的迹象；DB 门控用例本机未执行，其结论基于断言逐条查证，CI 以 `MAIL_CORE_REQUIRE_DB=1` 实跑仍为合并前的既定外部验证项（与前轮披露一致，非本轮新增问题）。

verdict: PASS
