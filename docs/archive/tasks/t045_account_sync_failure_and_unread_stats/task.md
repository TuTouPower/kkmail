---
tid: "t045"
slug: "account_sync_failure_and_unread_stats"
title: "修复故障账号目录展示与未读统计聚合及跟进任务载荷"
status: "done"
branch: "t045_account_sync_failure_and_unread_stats"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "f925d16094950ec856dc837319e40c15b91dbfe8"
depends_on: ""
conflicts_with: ""
note: "来源 p027；用户确认全局/分组未读汇总排除禁用或同步失败无目录账号，含 worker 跟进任务 payload 修复。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 根因修复与逻辑落地：
   - 侧栏空目录与故障展示（AC-001）：改造 `AccountFolders`，在 `folders.length === 0` 时按 `sync_status` 区分“同步失败，请检查账户设置”与“暂无文件夹”提示，不再单独裸露虚拟“未读邮件”按钮。
   - 故障账号聚合排除（AC-002）：在 `query_global_inbox_stats` 与 `query_group_inbox_stats` 查询中加入 `sync_enabled` 与 `sync_status`，排除已禁用或同步/认证失败且无目标文件夹的账号后计算全局/分组未读汇总；故障账号自身单独查询仍返回 null；统一 `MessageList.tsx` 与 `Sidebar.tsx` 对 0 目录与故障账号的统计语义。
   - 网易 IMAP 登录失败判定（AC-003）：在 `ImapProvider._connect` 捕获 `imaplib.IMAP4.error` 时增加匹配 `login error or password error` 抛出 `PermanentAuthError`，阻断 8 次无效重试并使账号置为 `auth_failed` 及 `sync_enabled=False`。
   - 空文件夹首次同步统计初始化（AC-004）：在 `apply_metadata_page` 中增加若 `FolderStats` 尚不存在即触发 `recompute_folder_stats`，使空目录立即初始化 `FolderStats(total_count=0, unread_count=0)`。
   - Worker 跟进重入队 payload 修复（AC-005）：在 `_evaluate_result` 中过滤内部 `_followup_*` 临时键，完整保留原业务 `payload`（如 `folder_id`），杜绝任务跟进时的 `KeyError`。
2. 规范与文档同步：更新 `docs/blueprint/conventions.md` §七.4「未读数未知语义」，固化故障账号聚合排除与空目录统计初始化契约。

## Review 处置

### Round 1 (2026-10-23T22:20:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`(cd src/frontend && npm test && npx tsc -b && npm run build && npm run lint)` 39 文件 262 项全通；`scripts/run-mail-core-tests.sh unit` 309 项全通；`pytest .repo_template/tests -q -m contract` 150 项全通；`(cd src/desktop && npm test)` 全通。
- 黑盒：`npm --prefix src/frontend run test:e2e`（14 项全部通过）；`python3 scripts/run_full_stack_e2e.py`（8 项全栈端到端测试全部通过）。
- review：`review_code.md` PASS（0 finding），`review_test.md` PASS（0 finding），指纹一致。
- AC 证据：见 `handoff.json`

### 结果摘要

- 修复故障与未同步账号在侧栏中空目录误显虚拟未读入口缺陷，在全局与分组未读汇总中排除故障无目录账号以恢复正常账号真实统计，支持网易 IMAP 永久密码错误识别、空目录统计初始化与 worker 跟进载荷保留。遗留：无。
