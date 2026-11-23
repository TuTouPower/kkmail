# Task review t087（reviewer_focus: 代码）

- task：`t087_connectivity_breaker_and_error_classification`
- spec：`docs/tasks/t087_connectivity_breaker_and_error_classification/task.md`
- diff_anchor：`82b86fb716e34a0fe71bbc317bad75ac212f21e5`
- target：`git diff 82b86fb716e34a0fe71bbc317bad75ac212f21e5`
- round：1
- reviewed_at：2026-11-23T11:57:10+08:00
    reviewed_scope: 50883764759a5019

## Findings

### t087_code_f001 - 有文件夹账号的健康提示盲区未修复

- 严重度：important
- 锚点：AC-004（侧栏在账号有文件夹时也按 `credential_state` / `connectivity_state` 显示凭据失效、网络不可达或重试提示）
- 位置：`src/frontend/src/components/Sidebar.tsx:271-277`、`:1171`
- 问题：`accountHealthNotice(account)` 在 `:271` 计算，但唯一渲染点 `:272-277` 整体位于 `if (folders.length === 0)` 内。只要账号有至少一个文件夹，代码直接走 `folderMap` 渲染，`connectivity_state==='unreachable'` 的「网络连接不可用，系统正在重试」与 `degraded` 的「网络异常，正在重试」均不显示。账号行 `:1171` 仅对 `credential_state==='invalid'` 渲染告警图标，对 `unreachable` / `degraded` 无任何可见提示。相对 anchor 的 `git diff --name-status` 共 15 个文件，全部位于 `docs/`、`src/mail_core/`、`tests/`，**无任何前端文件改动**；p088 遗留的 `Sidebar.tsx:271-277` 盲区原样保留。可复现：账号 `credential_state=valid`、`connectivity_state=unreachable`、folder-stats 返回 ≥1 个文件夹 → 侧栏健康文案缺失，与 AC-004 声明相反。
- 建议：将 `notice` 渲染移出 `folders.length === 0` 分支，在 `AccountFolders` 文件夹树之前按 `notice` 优先渲染；或把 `connectivity_state` 提示并入 `renderAccount` 账号行，与凭据态图标并列。两种方案都必须让前端改动进入本 task diff。

### t087_code_f002 - 5 分钟窗口叠加 5 分钟跨度使 unreachable 在真实 backoff 下不可达

- 严重度：important
- 锚点：AC-001（5 次传输失败按真实 `backoff_seconds` 序列推进须升级 `unreachable`，正反两例均覆盖）
- 位置：`src/mail_core/accounts/health.py:80-84`、`:168-170`；`docs/blueprint/conventions.md:160`
- 问题：`_failure_timestamps` 只保留 `stamp >= now - CONNECTIVITY_WINDOW` 的失败（`:83-84`），升级条件又要求 `now - min(stamps) >= CONNECTIVITY_WINDOW`（`:170`）。两者合取推出 `min(stamps)` 必须恰好等于 `now - 300s`——跨度必须精确压在窗口边界。按 Worker 真实重试序列 `backoff_seconds`（1,2,4,8,16,32,64,128…，`src/mail_core/sync/jobs.py:50-54`）推进：第 5 次失败累计 15s、第 9 次 255s，均 \<300s 保持 `degraded`；第 10 次（511s）窗口内只剩 2 个失败，再次 `degraded`。按 AC-001 指定的真实序列无论重试多少次都到不了 `unreachable`，连带 `recheck_unreachable`（`:185-211`）与 UI「网络不可达」文案在该路径成为死分支。实施方正例改用固定 60s 偏移（0,60,120,180,300）恰好卡边界通过，掩盖该差距；AC-001 要求的「按真实 backoff 序列推进的正例」实际不成立。
- 建议：解耦「连续性」与「跨度」判据——用 streak 首失败时间判定 ≥5 分钟跨度（相邻失败间隔超窗则重置 streak），窗口仅用于判定失败是否连续、成功清零；使真实 backoff 序列在累计 5 次且跨度达标时确实可达 `unreachable`。若坚持当前边界语义，须同步改写 AC-001 原文并说明仅多文件夹并发场景可达，但这不满足 AC 现状。

### t087_code_f003 - classify_failure 新建即高圈复杂度

- 严重度：minor
- 锚点：代码质量（圈复杂度标准 ≥15）
- 位置：`src/mail_core/sync/context.py:106-152`（`classify_failure`）
- 问题：本 task 新建函数，按手算近似 McCabe 约 21（BaseException 分支链、dict 分支、`or` / `and` 短路、try/except 与各 status/errno 判断）。401 判定、errno 白名单、5xx 判定与 `failure_code` 解析混在同一顺序链，后续新增 FailureDomain 容易因顺序调整引入误分类。
- 建议：按输入形态拆为 `_classify_exception` 与 `_classify_result_dict`，status/errno 判定表驱动化，降低顺序耦合。

## 结论

- 本轮新发现：3 条（2 条 important、1 条 minor）。
- 未进表的提示：
    - 文件过大：`src/mail_core/sync/idle_watcher.py` 732 行（anchor 719，净 +13）、`src/mail_core/worker/main.py` 716 行（anchor 690，净 +26），均 ≥400 且本 task 净增；`src/mail_core/sync/delta.py` 660 行但净 -3，不命中。按降级规则仅提示，不进 finding 表。
    - 健壮性：`src/mail_core/sync/idle_watcher.py:595-603` 的 `_record_connect_success` 吞掉所有异常仅 `log.debug`，IDLE 建连成功但重置失败时连接态可能滞留；已有日志且属 best-effort，未达 important，未进表。
    - 性能：`src/mail_core/worker/main.py:343-356` 先取全部 `unreachable` 账号 id 再逐个 `recheck_unreachable`，N+1 但受故障账号规模约束，当前无可观测缺陷。
    - 范围外观察：本轮未改前端、`tests/e2e/`；AC-005 的 E2E 断言缺失属测试 reviewer 轴，本报告不就测试文件出 finding。`test_cmd` / `blackbox_verify` 全量未独立重跑（worktree 无 `.venv`，浏览器 E2E 未执行）；已在主仓 venv 以 `KKMAIL_TEST_MODE=unit` 复跑 `test_account_health_state_machine.py`（13 passed）、`test_sync_backend_handler_isolation.py` / `test_sync_background_lineage.py` / `test_worker_loop.py`（18 passed / 22 skipped）。
- 总体判断：2 条 important 未解决（AC-001 正向语义在真实 backoff 下不成立，AC-004 前端盲区未改），且 3 条 AC 标 `TICK-VOID`，阻断 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VOID，re_verified。`health.py:83-84,170` 的窗口过滤与 `now - min(stamps) >= 300s` 合取要求首失败恰在 `now-300s`；按 `backoff_seconds` 序列推进（15s/255s/511s）始终 `degraded`，正例改用固定 60s 偏移压线，AC 声明未成立，见 f002。
- AC-002：TICK-VALID，re_verified。`context.py:114-152` 按类型/status/errno/`failure_code` 判定，`_NETWORK_ERRNOS`（`:20-37`）不含 ENOSPC/EMFILE/EACCES，自由文本不再参与；`delta.py:542-555`、`reconcile.py:225-233` 在脱敏边界写入 `failure_code`；`test_account_health_state_machine.py` 的 `test_failure_classification_ignores_free_text` 含反向与正向样本，本轮独立重跑通过。
- AC-003：TICK-VALID，re_verified。`health.py:124-143` 成功时 pop `CFG_FAILURE_TIMESTAMPS` / `CFG_LAST_CONNECTIVITY_ERROR` / `last_sync_error` 并置 `connected`；`:185-211` 在 15 分钟无新失败时把 `unreachable` 降为 `degraded`，`worker/main.py:333-358` 周期 sweep 调用，`idle_watcher.py:521` 建连成功复位。
- AC-004：TICK-VOID，re_verified。`Sidebar.tsx:271-277` 的 `notice` 仍只在 `folders.length === 0` 渲染，`:1171` 只覆盖凭据态；diff 无任何前端文件，见 f001。
- AC-005：TICK-VALID，re_verified。实现层：`health.py:49-61` 在连接态真实迁移时发 `account.updated`，前端 `useMailCoreRealtime.ts:130-131` 既有该事件使 `queryKeys.accounts` 失效，绕过 5 分钟 staleTime；`Sidebar.tsx:192-203` 的状态→文案映射仍准确。E2E 新增断言缺失属测试轴，见结论提示。
- AC-006：TICK-VOID，trust_prior。`conventions.md:160` 已与实现文本一致（本 reviewer 已核对），但「`test_cmd` 与 `blackbox_verify` 全量通过、无弱化断言」依赖实施侧打勾自述，本轮未独立重跑全量门禁（worktree 无 `.venv`，浏览器 E2E 未执行），证据不足。
- AC-007：TICK-VALID，re_verified。`docs/specs/mail_sync_and_storage.md` front matter 已登记 t087 且补连接健康条款，`docs/blueprint/testing.md:84` 已加对应门禁行；`docs/pending/p088_unreachable_accumulated_failure_false_positive.md:7,29` 为 `fix_ref: "t087"` / `resolution=transferred`，闭环指向成立。

coverage = 6/7

verdict: FAIL

## Round 2 (2026-11-23T12:08:20+08:00)

reviewed_scope: 5a7759dd5b00df9d

### 前轮 finding 复核

- t087_code_f001（important，同意撤回）：独立复核确认 Round 1 事实有误。`Sidebar.tsx:271-277` 不是唯一 notice 渲染点：有文件夹分支的返回体 `Sidebar.tsx:348-364` 在 `:350` 于文件夹树前渲染 `{notice && <div role="status">{notice.text}</div>}`。该文件不在本 task diff，anchor 处为同一实现。`Sidebar.test.tsx:192-197` 默认给 acc-1 返回 4 个文件夹；`Sidebar.test.tsx:1214-1224`（对应 Round 1 引用的 anchor `:1200/1212`，因 mockApi 增行整体后移 14 行）在未传 `emptyFoldersAcc1` 时同时断言 `toContain('网络连接不可用，系统正在重试')` 与 `toContain('收件箱')`，证明有文件夹时提示与文件夹树并存。同意撤回，AC-004 由既有实现满足。

- t087_code_f002（important，已消除）：`health.py:80-86` 新增 `_failure_streak`，仅当 `now - max(stamps) > 300s` 才重置 streak；`health.py:170-175` 改用 `len(stamps) >= 5 and now - min(stamps) >= 300s` 升级，去掉了 Round 1 指出的「窗口过滤 + 边界跨度」合取。按 `jobs.py:50-54` 的真实 `backoff_seconds`（1,2,4,…,512s，封顶 3600s）推进，第 10 次失败落在 `t=511s`、相邻间隔最大 256s 未触发重置、跨度 511s ≥ 300s → `unreachable`；跨天序列间隔 86400s > 300s，每次 streak 重置为 `[now]`，始终 `degraded`。实跑 `tests/mail_core/test_account_health_state_machine.py` 14 passed（含 `test_connectivity_failure_escalates_across_real_backoff_sequence` 与 `test_connectivity_failure_does_not_accumulate_across_days`）。缺陷已消除。

- t087_code_f003（minor，已消除）：`context.py` 的 `classify_failure` 收窄为按输入形态分发至 `_classify_exception` / `_classify_result_dict`，401/errno/5xx 顺序链已拆分，新建函数手算近似圈复杂度回落到低位（\<10）。缺陷已消除。

### Findings

本轮新发现 1 条（minor）。

### t087_code_f004 - 升级路径 docstring 仍称失败须落在单一窗口内

- 严重度：minor
- 锚点：文档与规格一致性（注释与实现不一致）；行为缺陷不成立，不阻断
- 位置：`src/mail_core/accounts/health.py:157-160`
- 问题：`record_connectivity_failure` 的 docstring 写「failures all fall inside one CONNECTIVITY_WINDOW and span that window」。f002 修复后 `_failure_streak`（`:80-86`）不再把 stamps 裁剪到窗口，`record_connectivity_failure`（`:170-175`）只要求相邻失败间隔 ≤300s 且首失败距今 ≥300s。按真实 backoff 第 10 次失败时 stamps 跨度 511s，无法落入任何单一 300s 窗口，却会升级 `unreachable`。注释错述了刚修复的状态机语义；维护者据此回改会重新引入 f002 缺陷。
- 建议：把 docstring 改为与 `_failure_streak` 一致的表述，例如「相邻失败间隔超过窗口才重置 streak；streak 内累计 ≥5 次且首失败距今 ≥ 窗口才升级」。

### 未进表的提示

- 文件过大：`src/mail_core/sync/idle_watcher.py` 732 行（anchor 719，净 +13）、`src/mail_core/worker/main.py` 716 行（anchor 690，净 +26），均 ≥400 且本 task 净增；按降级规则仅提示，不进 finding 表。`context.py` 当前约 180 行，未超阈值。
- 圈复杂度：`classify_failure` 拆分后无函数命中手算 ≥10 的密集分支，`_classify_exception` 约 7–8，不进表。
- 健壮性（沿用 Round 1 判断）：`idle_watcher.py:_record_connect_success`（`:590-602`）吞掉所有异常仅 `log.debug`，IDLE 建连成功但重置失败时连接态滞留；best-effort 且有日志，未达 important，不进表。
- 性能：`worker/main.py:333-358` 先取全部 `unreachable` id 再逐个 `recheck_unreachable`，N+1 但受故障账号规模约束，无可观测缺陷。
- 语义观察（非 finding）：AC-001 的「同一滑动窗口」落地为「相邻失败间隔 ≤ 窗口」，而非「5 次失败总跨度 ≤ 窗口」；`docs/blueprint/conventions.md:160` 与关联 spec 已同步该语义，跨天反例仍成立，不构成 AC 违背。
- 门禁复跑范围：本轮独立重跑后端 unit 全量 1466 passed / 497 skipped（其中状态机 14 passed、分类与 worker 18 passed / 22 skipped）；浏览器 E2E 与 `blackbox_verify` 未在本 worktree 重跑，见 AC-006 的 `trust_prior`。

### overall 与 next_action

- 总体判断：3 条前轮 finding 中 f001 同意撤回、f002/f003 已消除；本轮仅 1 条 minor 文档不一致（f004），无未解决 critical / important → 本报告 `verdict: PASS`。
- 机器门禁预期：f004 尚未进入 `progress.md` 处置表，`overall` 将判 INCOMPLETE，待实施方登记后复核。
- next_action：complete_disposition（在 Round 2 处置表登记 `t087_code_f004`，可选择修复 docstring 记「已修」或按「撤回」说明）；处置后再跑 `task.py review-status`。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`health.py:80-86,170-175` 相邻间隔 >300s 才重置 streak、跨度 ≥300s 且 ≥5 次才升级；按 `jobs.py:50-54` 真实 backoff 第 10 次（t=511s）达 `unreachable`，跨天 86400s 间隔始终 `degraded`；状态机 14 passed。docstring 陈旧另见 f004。
- AC-002：TICK-VALID，re_verified。`context.py` 的 `_classify_exception` / `_classify_result_dict` 按类型、401、5xx、errno 白名单与 `failure_code` 判定，ENOSPC/EMFILE/EACCES 与自由文本落 `UNKNOWN`；`delta.py:548`、`reconcile.py:230` 写 `failure_code`；`handlers.py:176-190` 仅 TRANSPORT 调 `record_connectivity_failure`；误分类与正向样本随 14 passed / 全量 1466 passed 复验。
- AC-003：TICK-VALID，re_verified。`health.py:132-143` 成功清 `CFG_FAILURE_TIMESTAMPS` 与诊断并置 `connected`；`:187-211` + `worker/main.py:333-358` 15 分钟无新失败把 `unreachable` 降 `degraded`；`idle_watcher.py:520-521` IDLE 建连成功复位，满足有界复核。
- AC-004：TICK-VALID，re_verified。`Sidebar.tsx:350` 在 `folders.length>0` 分支、文件夹树前渲染 `notice`；`Sidebar.test.tsx:1214-1224` 默认 4 文件夹下断言红字与「收件箱」并存。前轮 f001 同意撤回。
- AC-005：TICK-VALID，re_verified。`health.py:49-61` 连接态迁移发 `account.updated`（`OutboxEventType.ACCOUNT_UPDATED = "account.updated"`），`useMailCoreRealtime.ts:130-132` 使 `queryKeys.accounts` 失效，绕过 5 分钟 staleTime；组件层覆盖见 `Sidebar.test.tsx:1226-1242`，E2E 属测试轴。
- AC-006：TICK-VALID，trust_prior。本 reviewer 独立重跑后端 unit 全量 1466 passed / 497 skipped，核对 `conventions.md:160` 与实现一致、diff 无弱化断言或临时补丁；`blackbox_verify` 浏览器 E2E 未在本 worktree 重跑，依赖实施侧记录（progress.md:49）。
- AC-007：TICK-VALID，re_verified。`docs/specs/mail_sync_and_storage.md` front matter `tasks` 含 t087 且补连接健康条款；`docs/blueprint/testing.md` 新增门禁行；`docs/pending/p088_unreachable_accumulated_failure_false_positive.md` 为转办闭环。

coverage = 6/7

verdict: PASS

## Round 3 (2026-11-23T12:13:19+08:00)

reviewed_scope: 3776754e0fb6f322

### 前轮 finding 复核

- t087_code_f004（minor，已消除）：`src/mail_core/accounts/health.py:155-162` 的 `record_connectivity_failure` docstring 已改为「相邻失败间隔超过窗口才重置 streak；streak 内累计 ≥ 阈值且首失败距今 ≥ 窗口才升级」。本轮独立核对：docstring 的「no adjacent gap larger than `CONNECTIVITY_WINDOW`」「A gap larger than the window starts a fresh streak」与 `_failure_streak`（`health.py:80-86`，`now - max(stamps) > CONNECTIVITY_WINDOW → []`）一致；「a streak has `CONNECTIVITY_FAILURE_THRESHOLD` failures ... and a first-failure-to-now span at least that window」与升级条件（`health.py:171-175`，`len(stamps) >= 5 and now - min(stamps) >= CONNECTIVITY_WINDOW`）一致。按真实 backoff 第 10 次失败 t=511s 升级、跨天间隔 86400s 始终 `degraded` 的语义在 docstring 中无残留错述。修复为纯注释改动，不触及控制流。缺陷已消除。

### Findings

本轮新发现 0 条（finding 续编起点仍为 `t087_code_f005`，本轮未触发）。

### 未进表的提示

- 文件过大：`src/mail_core/sync/idle_watcher.py` 732 行（anchor 719，净 +13）、`src/mail_core/worker/main.py` 716 行（anchor 690，净 +26），均 ≥400 且本 task 净增；按降级规则仅提示，不进 finding 表。`context.py` 180 行、`health.py` 226 行均未超阈值。
- 圈复杂度：`classify_failure` 拆分后无函数命中手算 ≥10 的密集分支，`_classify_exception` 约 7–8，不进表。
- 健壮性（沿用前轮）：`idle_watcher.py:_record_connect_success` 吞异常仅 `log.debug`，best-effort 且有日志，未达 important，不进表。
- 性能：`worker/main.py` 逐个 `recheck_unreachable` 为 N+1，受故障账号规模约束，无可观测缺陷。
- 门禁范围：本轮未独立重跑全量门禁；Round 2 已重跑后端 unit 1466 passed / 497 skipped，本轮相对 Round 2 仅 docstring 注释变化，不改变可测行为；浏览器 E2E 与 `blackbox_verify` 仍依赖实施侧记录（见 AC-006）。

### overall

- 前轮唯一 finding `t087_code_f004` 已消除；本轮 0 新 finding；7 条 AC 打勾全部有效（TICK-VALID）。
- 总体判断：无未解决 critical / important，无残留 minor → 本报告 `verdict: PASS`。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`health.py:80-86` 相邻间隔 >300s 才重置 streak、`:171-175` 累计 ≥5 且首失败距今 ≥300s 升级；按 `jobs.py:50-54` 真实 backoff 第 10 次（t=511s）达 `unreachable`，跨天 86400s 间隔始终 `degraded`；docstring 现已与语义一致（见前轮复核）。
- AC-002：TICK-VALID，re_verified。`context.py:106-158` 的 `_classify_exception` / `_classify_result_dict` 按类型、401、5xx、errno 白名单与 `failure_code` 判定，`_NETWORK_ERRNOS`（`:22-42`）不含 ENOSPC/EMFILE/EACCES，自由文本不参与分类。
- AC-003：TICK-VALID，re_verified。`health.py:126-145` 成功清 `CFG_FAILURE_TIMESTAMPS` 等诊断字段并置 `connected`；`:188-214` + `worker/main.py` 15 分钟无新失败把 `unreachable` 降 `degraded`；IDLE 建连成功复位。
- AC-004：TICK-VALID，re_verified。`Sidebar.tsx:350` 在 `folders.length>0` 分支、文件夹树前渲染 `{notice && ...}`；`:272-274` 为 `folders.length===0` 分支。该文件不在本 task diff，anchor 处同一实现。
- AC-005：TICK-VALID，re_verified。`health.py:49-61` 连接态真实迁移发 `account.updated`（`OutboxEventType.ACCOUNT_UPDATED`），`useMailCoreRealtime.ts:130` 使 `queryKeys.accounts` 失效，绕过 5 分钟 staleTime；E2E 属测试轴。
- AC-006：TICK-VALID，trust_prior。本 reviewer 本轮未独立重跑全量门禁；Round 2 已重跑后端 unit 1466 passed / 497 skipped，`conventions.md:160` 契约文本已与实现一致且 diff 无弱化断言；本轮相对 Round 2 仅 docstring 注释变化。
- AC-007：TICK-VALID，re_verified。`docs/specs/mail_sync_and_storage.md` front matter `tasks` 含 t087 且补连接健康条款；`docs/blueprint/testing.md` 新增门禁行；p088 转办闭环指向 t087。

coverage = 6/7

verdict: PASS
