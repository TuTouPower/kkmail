# 历史交接

由 `repo-hygiene` 从 `docs/handoff.md` 迁入。**只追加**，禁止截断或改写已归档段落。

## 2026-10-22T02:48:00+08:00 agent → developer

- 当前焦点：采用 repo_template 模板完成全仓工程化改造、目录架构分流与门禁对齐
- branch：main
- head_commit：784f7a0494cf3e51247ffbe2e684073ae0315da1
- 已完成：
    - 源码收拢：后端、前端与桌面端源码全量收敛至 `src/`（`src/mail_core/`, `src/frontend/`, `src/desktop/`）。
    - 测试归位：E2E 测试从 `src/frontend` 迁出至全局测试目录 `tests/e2e/`，彻底净化源码目录；配置根目录与前端的 Playwright 联动。
    - 契约归位：OpenAPI 模式归入 `schemas/openapi.json`，同步全量脚本与自动化校验。
    - 资产归位：删除废弃皮肤目录 `data/skins/`；所有截图与设计文档收入 `assets/img/` 与 `assets/DESIGN.md`。
    - 配置归位：环境示例迁至 `config/.env.example`，根目录保留便捷软链。
    - 文档重构：长期真相整合写入 `docs/blueprint/`（架构、领域、约定、决策、测试）；人类使用手册规范放入 `docs/guides/`；已决策项全量挪入 `decisions.md` 并清理已做完待办；生成 3 篇带行为 AC 的生效 Spec（`auth_and_session`, `mail_sync_and_storage`, `inbox_ui_and_search`）并登记入 `docs/specs_index.md`。
    - 工具链落地：同步模板源最新提交 `658a825`，生成技能软链与 `.opencode/commands/` 命令薄层，执行 `install-hooks` 激活 `core.hooksPath`。
    - 缺陷修复：解决 Docker 构建中 TypeScript 与 openapi-typescript 的 peer 依赖冲突，修复桌面端与运维脚本中的硬编码旧路径。
- 未完成：无
- 陷阱：
    - 单独运行 Python 脚本或 Alembic 时需确保 `PYTHONPATH=src`（脚本与 env.py 已内置保护，裸跑命令时请留意）。
    - Playwright E2E 测试依赖 `src/frontend/node_modules` 依赖，运行时已自动配置 `NODE_PATH`，请通过 `npm --prefix src/frontend run test:e2e` 执行。
- 下一步：
    - 等待用户最终代码审查，确认无误后执行原子提交与推送。

---

# 项目交接记录（最新）

本文件只保留当前有效一节。过时段落由 `repo-hygiene` 迁入 `docs/archive/handoff.md`。

## 2026-10-22T06:00:00+08:00 agent → developer

- 当前焦点：完成 t001-t003 业务实施归档、多轮密集审查归档及采纳项修复实施
- branch：main
- head_commit：ded525b26aa66996acf8fb2bbebcd7b4a885f47f
- 已完成：
    - 业务任务完成与归档：
        - t001 (mail_core_sent_query): 后端支持 folder_role 查询已发邮件，完成 IMAP Sent 目录映射。
        - t002 (frontend_favorites_views): 前端个人收藏重构为收件箱未读与已发三折叠树形视图。
        - t003 (reader_toolbar_and_context_menu): 重构邮件详情居中工具栏并支持邮件列表右键快捷菜单。
    - 缺陷修复：闭环修复 p001-p004 及 p005-p007，涵盖垃圾箱交互、空正文提示、过滤谓词下推与设置表单同步。
    - 审查与决策归档：完成全仓高强度多 bundle 交叉审阅，形成采纳决策表并归档至 `docs/reviews/review_20261022_052842/`。
- 未完成：
    - 按采纳决策表分批实施已批准采纳项。
- 陷阱：
    - 各实施分支应在独立 worktree 中操作，严格遵循各模块读写边界与测试门禁。
- 下一步：
    - 推进各模块采纳项修复分支的验证与集成。

---

## 2026-10-25T05:22:51+08:00 agent → developer

- 当前焦点：逐项实施 `docs/reviews/review_20261025_020805/adoption_decision.md` 中已批准项；每项在独立分支/worktree 中实现、验证、提交并快进合入 `main`，不 push。
- branch：main
- head_commit：aa126fb827a3ab525640fe7779a32a9b5f3aaa1c
- 已完成：A1–A60 均可从 main 提交的 `Adoption-ID` trailer 追溯；A6 本次更新交接记录并归档旧段落。
- 未完成：A61–A296；按 adoption 决策顺序继续，已合入项不重复执行。
- 陷阱：测试数据库只能经 `scripts/run-mail-core-tests.sh` 及其 owned database guard 操作；不要直连业务数据库。
- 下一步：继续 A61，保持每项独立 commit 与 main 快进合并。

---

## 2026-10-26T06:55:55+08:00 agent → developer

- 当前焦点：`docs/reviews/review_20261026_commits/` 修复计划（R01–R18）与 pending p053–p057 已全部实施完毕，仅本地提交、未 push；无进行中的实现工作。
- branch：main
- head_commit：cd90a5ca（实现完成点；本节所在的收尾 docs 提交为其后继）
- 已完成：按 repair_design 工作包 A–I 顺序落地全部 R01–R18 与 p053–p057，共 14 个实现提交（清单见 `.scratch/fix_progress.log` 与 git log）；p053–p057 已由 pending.py 归档至 `docs/archive/pending/`（处理：fix/review-20261026-commits）；新迁移 `20261026_0025`（同步执行跟踪）、`20261026_0026`（outbox 保留水位）；OpenAPI 现为 41 paths。
- 验证：后端 unit 模式全量 815 passed / 280 skipped / 2 failed（2 项为沙箱 DNS 把测试域名解析进受限网段触发 SSRF 守卫，环境问题、测试未改动）；前端 47 文件 / 445 测试全过，tsc、oxlint、openapi:check、css:check、dep-locks --check 全绿；桌面端 11 个测试文件 10 个通过，`clipboard.test.js` 需真实 Electron 运行时、本机 `src/desktop/node_modules` 为空，未能运行。
- 未完成/环境受限：本机无 Docker，PG 门控测试（279+ skipped 的主体）与真实全栈 E2E 未运行，需在有 PG 运行时的环境补跑 `scripts/run-mail-core-tests.sh` 全量与真实 E2E 后再谈部署。
- 陷阱：沙箱 DNS 会把 `*.test` 域名解析进私网段，凡断言 SSRF 守卫放行测试域名的用例在本机必失败，勿据此改生产校验；`scripts/check_dep_locks.py` 不带 `--check` 会按本机路径重写 lock 文件头，勿误提交。
- 遗留裁决：p055 收敛只封前端新增入口，后端 API 直接创建 `provider=gmail` 是否封堵未定（见 `docs/specs/account_connection.md` 2026-10-26 节）。
- 下一步：无既定下一步；如要部署，先在 PG 环境补跑全量门禁与恢复演练。

## 2026-10-26T09:41:39+08:00 agent → developer

- 当前焦点：针对 822db4ba 的审阅核实清单（前批 3 条 + 后批 11 项，去重共 13 个已核实缺陷，编号 R13-01–R13-13）已全部修复完毕，仅本地提交、未 push；无进行中的实现工作。
- branch：main
- head_commit：f7bacbc6（实现完成点；本节所在的收尾 docs 提交为其后继）
- 已完成：13 项逐项独立提交（清单见 `.scratch/fix_progress.log` 与 `git log 822db4ba..HEAD`，共 12 个实现/测试提交）：批一 P1——备份 resume 在目标锁内重读 operation log 按最新 stage 决策（16140691）、sync 结算统一全局锁序消除多 target 死锁（34b5538d）、checkpoint 代际以登记出生序校验阻止 G1→G2→G1 回退（bffd35f8）、连接预算集成测试终止时序去无界阻塞（168dddaf）；批二 sync 集群——孤儿巡检定罪前惰性复查 live 集合（79c64cdc）、remote_push 容量分支回传 followup_coalesced（683fe7b2）、全量扫描复用纳入 metadata 在途 job 的根代际（cb59ccf4）；批三微软接入链——极简流补 token scope 与 inbox 可达校验（dfe3327e）、OAuth metadata 下发 effective client id 且授权/换码两步同源（ae44a8d7）、redirect_uri 显式透传原样使用（03f3b58e）、mail 缺失时仅消费者邮件域 UPN 受限回退（84a95819）；批四——测试契约迁移至 head 20261026_0026 / outbox 新契约 / 桌面简化流编排（f7bacbc6）。整数 SSE ID（已迁 v2 字符串游标）与 traffic_class mock 经核实无问题，未动。
- 验证：后端 unit 模式全量 797 passed / 271 skipped / 3 failed（3 项已在基线 822db4ba 用独立 worktree 原样复现，均为既存环境失败，非本轮引入）；前端 47 文件 / 442 测试全过，tsc、oxlint、openapi:check 全绿；每项均有先红后绿的专项回归测试（前端 exchange 载荷、迁移 head 断言等语义变更处按仓库规则整体替换并留 REPLACED 注记）。
- 未完成/环境受限：本机无 Docker、无 `MAIL_CORE_DATABASE_URL`，PG 门控测试全部 skip：多 target 死锁仅做锁序语句级单测（PG 双事务并发实测未做）、迁移校验与 outbox wake 的 PG 用例未实跑、桌面 Electron 集成测试仅完成编排更新与语法/自跳过校验（真实 Electron + PG 套件未跑）。补跑须在有 PG 运行时的环境执行 `scripts/run-mail-core-tests.sh` 全量与桌面集成。
- 遗留裁决：p055 已闭环——836d01fc 已移除后端 gmail provider 引擎与 `AllowedProvider` 中的 gmail 条目（现为 imap/graph/memory/stub），API 直接创建 `provider=gmail` 已不可能，此前"是否封堵未定"的裁决就此了结（Gmail 仅保留 IMAP 应用专用密码接入）。
- 下一步：无既定下一步；是否 push 由用户决定。

---

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
