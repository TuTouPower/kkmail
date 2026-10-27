---
tid: "t061"
slug: "idle_inbox_and_all_folder_status_patrol"
title: "IDLE 收件箱实时监听与全文件夹 STATUS 周期巡检"
status: "done"
branch: "t061_idle_inbox_and_all_folder_status_patrol"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "327acc0250f26c71d7ad2b777e876b92ff79c484"
depends_on: ""
conflicts_with: ""
note: "由 t059 与 t060 按用户指令合并而来（task-merge）：IDLE 负责收件箱实时、全文件夹 STATUS 巡检负责其余文件夹的周期发现；t059/t060 已 drop 归档，编号不复用; 2026-10-28 用户确认设计细化：IDLE 独立配额（默认 32、热账号优先、不占 8 个任务槽位）；STATUS 基线复用 SyncCheckpoint.cursor JSONB，不新增迁移；imaplib IDLE 按扩展 Commands + socket select/poll 可打断循环方向验证；账号量级现状约 100、规划近千"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- attempt 1 / execution_id 7d1ae864081c46179fd9b4b2f0b37ed5；base main@327acc02；分支 t061_idle_inbox_and_all_folder_status_patrol。
- 实施前先解 4 项 UNVERIFIED-SPIKE 并回填 spec（结论见 spec 未知契约清单）：imaplib IDLE 原语经 fake IMAP 服务器原型实证（产物 .scratch/idle_spike/，收尾复跑 ALL SPIKE CHECKS PASSED）；`preflight t061 --require-verified` PASS 后进入实施。
- 实现形态：新模块 src/mail_core/sync/idle_watcher.py（IDLE watcher：独立配额 32、热账号优先 + 滞回、抖动退避、状态经 AppSetting worker:idle_state 发布）与 src/mail_core/sync/patrol.py（全文件夹 STATUS 巡检：基线存 SyncCheckpoint.cursor 的 last_status/last_probe_at、不新增迁移）；providers/base.py 增 FolderStatus 与 probe/open_idle_session 契约，imap.py 实现 IDLE 会话（扩展 Commands 注册 IDLE + 专属读线程 + 控制线程唯一写者）与 STATUS 探测（走任务槽位 permit），graph.py 实现计数探测，stub_memory.py 实现内存探测；t058 集中配置新增 idle_* 与 folder_patrol_* 共 11 项（config/models.py、loader.py、config/.env.example）；worker/main.py 接入 watcher 启停、巡检 sweep 与 held 账号跳过收件箱轮询。blueprint 已同步：docs/blueprint/architecture.md 与 docs/specs/mail_sync_and_storage.md 新增 t061 章节。
- 基线先测：实施前于 base 327acc02 跑后端 unit 全量为 1477 passed / 20 failed / 288 skipped；最终全量 1508 passed / 20 failed / 305 skipped，失败集与基线逐条一致、零新增（其中基线尾部 6 个失败名经纯净基线 worktree 定向复跑确认同为基线失败）。
- 环境限制（如实记录）：本机 Docker 不可用，PG Docker 门禁与全栈 e2e 未跑；便携 PG 16.2 在本沙箱因 nobody 穿越权限、chown 禁止、userns initdb 失败三路均无法启动，直连 127.0.0.1:5432–5434 均 connection refused，故 17 个 DB 门控测试按仓库惯例在 unit 模式 skip（CI 以 MAIL_CORE_REQUIRE_DB=1 把守）；本机缺 md_kx 二进制，格式门禁以 git diff --check 兜底（clean）。前端 e2e 冒烟 18 failed 与未改动的主仓检出完全一致，属环境性既存问题；桌面 packaged 测试因缺 electron 未跑（本 task 零桌面改动）。
- 黑盒：AC-016 为 [deploy] 项，本地替代验证 .scratch/blackbox_t061.py PASS（真实 ImapProvider + fake IMAP 服务器：IDLE 唤醒 0.20s、STATUS 变化维度判定正确、无变化零判定），部署实测待上线环境执行。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-28T04:56:26+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t061_code_f001|important|已修|巡检失败路径统一经 _record_attempt 推进 last_probe_at 并累计失败计数，选择逻辑以 critical 优先组消费 max_unprobed_s，失败集不再饿死轮转|src/mail_core/sync/patrol.py|
|t061_code_f002|minor|已修|巡检初始查询改为 Folder/Account/SyncCheckpoint 单次 join，消除逐文件夹 N+1|src/mail_core/sync/patrol.py|
|t061_test_f001|minor|已修|AC-013 测试断言每轮 probed remote_id 精确集合与全覆盖无重复，另加失败集饿死回归与 AC-014 尝试时钟断言|tests/mail_core/test_t061_status_patrol.py|
|t061_test_f002|minor|已修|新增管理器级断线恢复用例（首会话抛 IdleSessionDisconnected 后重建并回到 held/idling）|tests/mail_core/test_t061_idle_watcher.py|
|t061_test_f003|minor|已修|新增 held 账号跳过收件箱轮询用例与 permit 计数用例（IDLE 会话 0 permit、STATUS 探测 1 permit）|tests/mail_core/test_t061_idle_watcher.py / tests/mail_core/test_t061_imap_idle_probe.py|
|t061_test_f004|minor|已修|新增凭据指纹变更重建、paused 关闭、禁用再启用恢复三分支用例|tests/mail_core/test_t061_idle_watcher.py|
|t061_test_f005|minor|已修|新增 IDLE 开关关闭的 manager noop 纯测试（session factory 被调用即失败）|tests/mail_core/test_t061_idle_watcher.py|
|t061_test_f006|minor|已修|新增 Graph probe 字段映射 3 例，AC-008 用例参数化 sent/drafts/trash/custom 四种 role；MemoryProvider 与默认 factory 残留转 Round 2 的 t061_test_f007|tests/mail_core/test_t061_graph_probe.py / tests/mail_core/test_t061_status_patrol.py|

### Round 2 (2026-10-28T05:12:25+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t061_code_f003|important|已修|blocked 退出路径经 _register_blocked 注销自身 _Watch 条目并记录 (指纹， 时刻），使指纹变化与 3600 秒过期重试真实可达|src/mail_core/sync/idle_watcher.py|
|t061_test_f007|minor|已修|新增 MemoryProvider probe 3 例与 _default_provider_factory 对 stub 账号返回 MemoryProvider 1 例|tests/mail_core/test_t061_memory_probe.py|

### Round 3 (2026-10-28T05:17:58+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t061_code_f004|minor|已修|_register_blocked 增加身份守卫：已被新 watch 替换的陈旧线程直接返回，不覆写 _blocked/_states/_watches|src/mail_core/sync/idle_watcher.py|
|t061_code_f005|minor|已修|_reconcile_once 开头清扫不在候选集且不在 _watches 的账号残留 _states/_blocked 条目|src/mail_core/sync/idle_watcher.py|

### Round 4 (2026-10-28T05:22:49+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t061_code_f006|minor|已修|_set_state 改为 (watch, state) 签名并加同一身份守卫，全部 5 个调用点改传 watch 本人，白盒用例扩展对应断言|src/mail_core/sync/idle_watcher.py / tests/mail_core/test_t061_idle_watcher.py|

### Round 5 (2026-10-28T05:26:07+08:00)

Round 5 零 finding（code 与 test 两路均 PASS，f001–f006 / f001–f007 全部复核已消除）。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足（AC-016 为 [deploy] 项，本地替代验证已完成，部署实测待上线环境执行）
- 测试：后端 unit 全量 1508 passed / 20 failed / 305 skipped，失败集与 base 327acc02 基线 20 条逐条一致、零新增；契约测试 189 passed；t061 专项 31 passed / 17 skipped（DB 门控，仓库惯例）；前端 531 passed + tsc + build 通过（本 task 零前端改动）；OpenAPI --check 无漂移；git diff --check clean。未跑：PG Docker 门禁与全栈 e2e（本机无 Docker、便携 PG 沙箱权限无法启动）、桌面 packaged（缺 electron）、md_kx 格式门禁（二进制缺失，以 diff --check 兜底）
- 黑盒：`.scratch/blackbox_t061.py` PASS（AC-016 本地替代：IDLE 唤醒 0.20s、STATUS 变化判定正确）；前端 e2e 冒烟 18 failed 与主仓未改动检出一致（环境性既存）
- review：full 级双路（code + test）共 5 轮，最终 verdict 均为 PASS；累计 finding 13 条（important 2、minor 11）全部已修并经独立复核消除
- AC 证据：见 `handoff.json`

### 结果摘要

- IDLE 收件箱实时监听（独立配额、热账号优先 + 滞回、抖动退避、能力门控、状态可观测）与全文件夹 STATUS 周期巡检（基线存 cursor JSONB、无变化零入队、轮转与未探测上限、失败隔离）已落地，两开关关闭即回到 t057 现状；AC-016 部署实测与 17 个 DB 门控测试的 CI 实跑（MAIL_CORE_REQUIRE_DB=1）为仅剩的外部验证项。
