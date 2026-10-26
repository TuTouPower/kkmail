# 项目交接记录（最新）

本文件只保留当前有效一节。过时段落由 `repo-hygiene` 迁入 `docs/archive/handoff.md`。

## 2026-10-26T20:26:27+08:00 agent → developer

- 当前焦点：第四轮审阅的 26 项已核实缺陷 + 1 项用户追加（Sidebar 搜索下点击文件夹被吞）已全部修复完毕，仅本地提交、未 push；无进行中的实现工作。
- branch：main
- head_commit：05d2cc84（实现完成点；本节所在的收尾 docs 提交为其后继）
- 已完成：27 项逐项独立提交（清单见 `.scratch/fix_progress.log` 与 `git log 2e29508c..HEAD`，共 28 个提交，R08 含一处测试 setup 跟进）：批一数据安全——IMAP reconcile 在 UIDVALIDITY 不可验证时中止对账（fc976b1e）、session_epoch 两条递增路径统一走凭据行锁（4a667d61）、密钥轮换纳入凭据锁协议防覆盖新 Token（5fcbd61a）、dispatcher 基线状态与游标值分离（c2dd992f + 5a4c57d5）、Graph 特殊文件夹按 well-known endpoint 的稳定 ID 分类（c8ea6af2）；批二并发——全仓统一 Target→Binding 锁序（671d3e11）、delta CursorInvalidError 把原请求转绑重建链待其终态才结算（7ceef0e5）、device-code 轮询的阻塞 HTTP 移出凭据锁事务（8951e5db）、archive open_session 失败穿透结算且不缓存未握手 provider（80d01605）；批三同步/性能——无 MODSEQ 时有界现存 UID 旗标扫描（8f46ecf5）、无本地订阅者时分发游标照常推进（37f80f49）、登录限流失败表加全局容量上限（e978d7cb）、reconcile 删除执行批量化（74471b77，200 条删除语句数 1221→27、结果与事件等价）；批四前端——旗标乐观更新按邮件串行 + 代际校验回滚（f68ab364）、MessageReader 订阅稳定化（39ae86a8）、同步冷却按目录独立（78a9ff04）、列宽拖拽卸载兜底清理（5ec60b4d）、滚动 rAF 节流（e23b1771）；追加——Sidebar 搜索在树导航行 pointerdown 时延迟到 click 后关闭（23f1064c）；批五死代码——后端 4 符号（3c4fdf93，其中 reconcile_account_writeback_and_stats 的唯一消费者是只测其自身的 AC-007 测试，按裁决规则连带删除并在 commit 注明）、前端 6 类（ef69ec28）；批六测试与门禁——附件 404 严格断言（7d8a5f1a）、validate_connection 补精确断言（918ecf1d）、FTS 断言真实命中 message_id（f7f0ca83）、folder stats 竞态与 global stats 改真 DB 测试（e39bf71a）、R09 四处测试装置修复（23ad7207）、默认门禁必须有测试 PG 且不再静默降级 unit（05d2cc84）。
- 验证：后端 unit 模式全量 812 passed / 280 skipped / 3 failed——3 项失败（test_create_account_serializes_slotted_dto_mock 的沙箱 SSRF/DNS、test_build_provider_imap_json_credentials_unpack、直跑模式下 test_setup_cleanup_failure_stops_suite 的子进程导入环境差异）均已在基线 2e29508c 用独立 worktree 以相同方式复现，为既存环境失败，非本轮引入；经官方 wrapper 的 unit 运行仅前 2 项失败。前端 46 文件 / 446 测试全过、tsc 全绿（基线 47 文件 / 442：F5 删除 canSendFrom 专用测试文件 1 个，本轮新增回归测试净增）。每项均有先红后绿的专项回归测试；语义变更处（R01 Graph 夹具、B3 计数语义）按仓库规则整体替换并留 REPLACED 注记。
- PG 实测口径（重要）：本机无 Docker，官方 PG pytest 门禁的 guard_database 强制 Docker 所有权记录，本地无法合法运行（禁止伪造）。替代验证：便携 PostgreSQL 16.2（127.0.0.1:5433）+ `.scratch/` 独立 harness 直调生产代码/测试函数，已实测 R02/R03 真并发交错、R07 删除与结算双事务死锁对照（旧码 DeadlockDetected、新码双双提交）、R04 重建失败反馈、R08 空流双 dispatcher、B5b 等价性 + 语句计数、T1/T3/T4/R09(a)(b)(c) 的 PG 门控测试函数。结论均为"PG 逻辑已实测、PG pytest 门禁未跑"，不得表述为门禁通过；补跑须在有 Docker 的环境执行 `scripts/run-mail-core-tests.sh` 全量。
- 未完成/环境受限：PG pytest 门禁套件与真实 E2E（Playwright、Electron）未在本机运行；R09(d) 仅更新 e2e 定位器（设置页 Escape 退出），未实跑 Playwright。
- 遗留事项：B5c(b) 已按简报裁决规则处理完毕（函数与其自测一并删除），无待裁决项。本轮无 push，等待用户指令。
- 下一步：无既定下一步；是否 push 由用户决定。
