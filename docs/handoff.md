# 项目交接记录（最新）

本文件只保留当前有效一节。过时段落由 `repo-hygiene` 迁入 `docs/archive/handoff.md`。

## 2026-10-26T09:41:39+08:00 agent → developer

- 当前焦点：针对 822db4ba 的审阅核实清单（前批 3 条 + 后批 11 项，去重共 13 个已核实缺陷，编号 R13-01–R13-13）已全部修复完毕，仅本地提交、未 push；无进行中的实现工作。
- branch：main
- head_commit：f7bacbc6（实现完成点；本节所在的收尾 docs 提交为其后继）
- 已完成：13 项逐项独立提交（清单见 `.scratch/fix_progress.log` 与 `git log 822db4ba..HEAD`，共 12 个实现/测试提交）：批一 P1——备份 resume 在目标锁内重读 operation log 按最新 stage 决策（16140691）、sync 结算统一全局锁序消除多 target 死锁（34b5538d）、checkpoint 代际以登记出生序校验阻止 G1→G2→G1 回退（bffd35f8）、连接预算集成测试终止时序去无界阻塞（168dddaf）；批二 sync 集群——孤儿巡检定罪前惰性复查 live 集合（79c64cdc）、remote_push 容量分支回传 followup_coalesced（683fe7b2）、全量扫描复用纳入 metadata 在途 job 的根代际（cb59ccf4）；批三微软接入链——极简流补 token scope 与 inbox 可达校验（dfe3327e）、OAuth metadata 下发 effective client id 且授权/换码两步同源（ae44a8d7）、redirect_uri 显式透传原样使用（03f3b58e）、mail 缺失时仅消费者邮件域 UPN 受限回退（84a95819）；批四——测试契约迁移至 head 20261026_0026 / outbox 新契约 / 桌面简化流编排（f7bacbc6）。整数 SSE ID（已迁 v2 字符串游标）与 traffic_class mock 经核实无问题，未动。
- 验证：后端 unit 模式全量 797 passed / 271 skipped / 3 failed（3 项已在基线 822db4ba 用独立 worktree 原样复现，均为既存环境失败，非本轮引入）；前端 47 文件 / 442 测试全过，tsc、oxlint、openapi:check 全绿；每项均有先红后绿的专项回归测试（前端 exchange 载荷、迁移 head 断言等语义变更处按仓库规则整体替换并留 REPLACED 注记）。
- 未完成/环境受限：本机无 Docker、无 `MAIL_CORE_DATABASE_URL`，PG 门控测试全部 skip：多 target 死锁仅做锁序语句级单测（PG 双事务并发实测未做）、迁移校验与 outbox wake 的 PG 用例未实跑、桌面 Electron 集成测试仅完成编排更新与语法/自跳过校验（真实 Electron + PG 套件未跑）。补跑须在有 PG 运行时的环境执行 `scripts/run-mail-core-tests.sh` 全量与桌面集成。
- 遗留裁决：p055 已闭环——836d01fc 已移除后端 gmail provider 引擎与 `AllowedProvider` 中的 gmail 条目（现为 imap/graph/memory/stub），API 直接创建 `provider=gmail` 已不可能，此前"是否封堵未定"的裁决就此了结（Gmail 仅保留 IMAP 应用专用密码接入）。
- 下一步：无既定下一步；是否 push 由用户决定。
