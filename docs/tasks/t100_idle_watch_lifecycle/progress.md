---
tid: "t100"
slug: "idle_watch_lifecycle"
title: "拆分 IDLE 席位策略与会话生命周期"
status: "done"
branch: "t100_idle_watch_lifecycle"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "7746212f8d96870d0b7e75fd1868c159993d1a27"
spec_source_sha: "7746212f8d96870d0b7e75fd1868c159993d1a27"
depends_on: ""
conflicts_with: ""
note: "p105: IDLE 会话、席位所有权与轮询兜底"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

### 2026-11-29 云端实施（attempt 1）

- 拆分落地：新增无 I/O 纯策略模块 `src/mail_core/sync/idle_policy.py`（`IdleCandidate`、`IdleWatcherConfig`、`backoff_delay`、席位分组/排序/滞回、`select_idle_holders`）；`idle_watcher.py` 重写为 `IdleWatchSession`（单账号单独拥有 provider 连接、续订、重连、通知与有界补偿）+ `IdleWatcherManager`（只拥有席位分配、关闭中资源登记与状态发布）。被替换的 `_Watch`、管理器侧 `_watch_loop` / `_enqueue_*` / `_set_state` / `_register_blocked` 与旧关闭线程簿记（`_closing_threads` / `_closing_readers` / `_closing_watches` 三件套）整体删除，由 `_ClosingResource`（执行线程 + reader 线程都退出才释放席位）取代，无转发层保留；全部 import 点（src 与 tests）已迁至新归属。
- 归属约束：会话经 host 回调 `session_state_changed` / `session_blocked` 报告，管理器以「登记实例即本人」校验后才提交状态或注销席位；迟到旧会话的报告被整体忽略（AC-002）。
- 占用与订阅分离：配额占用 = 活动会话 + 关闭中资源；轮询跳过集合 `held_account_ids()` 改由管理器已提交状态（`idling` / `changed`）派生——实施中曾以会话本地 `subscription_active` 标志派生，导致 held 先于状态提交翻转、与聚合状态瞬时不一致（AC-004 违规），已按根因改为单一事实源（已提交状态），并由 t061 既有 blocked 重试用例抓出该竞态后修复。
- 验证（云端 unit 模式，KKMAIL_TEST_MODE=unit）：新增 `tests/mail_core/test_t100_idle_watch_lifecycle.py` 6 用例（席位交接分阶段退出、旧会话迟到 block 不覆盖继任者、退避占用席位但恢复轮询、首连/重连/变化的后台去重键入队接线、补偿预算耗尽降级、停止后拒接新会话）全过；t061 可跑部分 15 用例、t095 idle 真实线程/stub IMAP 协议用例 6 用例全过；全量 unit 套件 1767 passed / 646 skipped（PG 门控）/ 2 failed，两条失败（`test_blob_permissions` 不可读子树、`test_system_health` 指标）在基线 7746212f 同样复现，属 root 环境假象，与本 task 无关。
- 环境阻塞：本机无可用 Docker（daemon 因缺 NET_ADMIN 起不来），仓库 PG 运行时 ownership guard 强制 Docker 托管实例，便携 PG 无法接入；真实 PG 部分（t061 全部 db_only：候选加载 SQL、补偿与 pending/claimed 去重合并、凭据轮换关闭等，及全量 PG 门禁）未在云端执行，已登记 p106 待本地复跑。AC 打勾依据为 unit 模式下可达的完整行为链（纯策略 + 真实线程 + stub 协议 + 入队接线断言）；`enqueue_job` 去重合并语义本身未被本 task 改动，其 PG 回归归 p106。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-29T00:37:12+08:00)

review_code overall PASS、review_test overall PASS（零 finding）；AC-001..AC-004 逐条 TICK-VALID。已修竞态（held 由已提交状态派生）经复审专项确认根除；行为等价对照除下表一条 minor 外无漂移。

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t100_code_f001|minor|遗留|stop() 关闭循环未 join 仅 reader 残留的关闭资源，停止等待语义弱一档；席位登记与配额不受影响，不涉任何 AC|p110|

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足（云端可达验证范围内；真实 PG 门禁复跑见 p106）
- 测试：unit 模式全量 1767 passed / 646 skipped（PG 门控）/ 2 failed（基线同复现的环境假象）；t100 新增 6 用例、t061 可跑 15 用例、t095 idle 6 用例全过；模板契约 387 passed / 2 failed（基线同复现）；PG 全量门禁未在云端执行（无 Docker），见 p106
- 黑盒：不适用——本 task 只动后端 IDLE 运行时与测试接缝，前端与 Compose 未改，blackbox_verify（前端 stubApi E2E）无受影响面
- review：Round 1 独立复审 review_code / review_test 均 PASS，AC-001..AC-004 全部 TICK-VALID，minor finding 1 条遗留 p110
- AC 判定：见 `task.md` 行内打勾

### 结果摘要

- IDLE 运行时完成策略/会话/管理器三分：`idle_policy.py` 纯策略、`IdleWatchSession` 单账号连接生命周期、`IdleWatcherManager` 席位与关闭资源与状态发布；归属守卫与占用/订阅分离落地，被替换实现无残留。
- 遗留：p106（真实 PG 门禁复跑）、p110（stop() reader join minor）。

### 长期文档闭环

- specs_index: t100 已登记于 `docs/specs/mail_sync_and_storage.md` front matter `tasks` 清单。
- blueprint：`architecture.md` IDLE 章节已补职责三分与占用/订阅分离；`testing.md` 已登记 IDLE 席位策略与会话生命周期验证行。
