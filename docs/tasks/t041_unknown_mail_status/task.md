---
tid: "t041"
slug: "unknown_mail_status"
title: "保留邮件未知状态并贯通统计展示"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "来源 p024；用户授权直接 main 修复。未知 provider 状态保存 NULL，不清洗历史数据。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 用户授权直接在 `main` 修复；实现包含 nullable 邮件状态/未读统计、API/codegen 与前端未知值分支、旧库无 flag 来源保留 null。实现已提交 `300d394`，审查 PASS；最终 PostgreSQL 全量 477 passed / 0 skipped；本轮不改写历史状态数据。

- 工具状态说明：`task.py edit` 无 status 参数，`start` 必须建立 worktree；用户明确要求直接 main，因此不创建假 worktree、不伪造 active/done。front matter 保持脚本登记的 backlog，实际实施与验证事实记录于正文。

- 补扫 IMAP FETCH：缺 FLAGS 保留未知，空 FLAGS 明确 false；完整 token 匹配避免扩展旗标误判。新增两入口回归，独立代码审查 Round 3 PASS。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T19:17:52+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t041_code_f001|important|已修|IMAP 扩展旗标不得靠子串变成系统状态，改为完整 token 匹配并覆盖两入口。|`f5ef673`|
|t041_code_f002|important|已修|搜索结果包含未知读状态时，未读统计传播 null。|`300d394`|
|t041_code_f003|important|已修|乐观回滚优先恢复缓存原值，避免旧 item 覆盖 null。|`300d394`|

最终代码 Round 3 与测试审查均 PASS，见 [review_code.md](review_code.md)、[review_test.md](review_test.md)。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部行为验收、审查与门禁通过；实现已在 main，pending 已闭环。
- 测试：PG 定向 migration/legacy/global stats 13 passed；最终 partial/race/detail 定向 19 passed。前端全量 260 passed；TypeScript、生产构建、lint、OpenAPI/CSS 检查通过。模板契约 149 passed / 1 skipped；桌面单元与打包冒烟通过。最终串行 PostgreSQL 全量 477 passed / 0 skipped（378.17s），运行 e9e0192dae624ce980a1ae3ee8fe66b3，测试库清理成功。
- 黑盒：stub E2E 13 passed；真实全栈 E2E 串行运行 8 passed。首轮与 stub 并行构建 dist 冲突导致 HTTP 500，定位后改为串行构建/运行并通过；未部署生产。
- review：代码与测试审查均 PASS，见 [review_code.md](review_code.md)、[review_test.md](review_test.md)。
- AC 证据：见下表；直接 main 实施，不生成或伪造 worktree `handoff.json`。

|AC|实际证据|
|---|---|
|AC-001|`test_unknown_mail_status.py` 真实 metadata apply/PG 首次三状态 NULL、明确 false 后未知更新不覆盖。|
|AC-002|API/codegen nullable 契约；MessageList 未知状态不显示未读/不自动写回，queries 乐观失败恢复缓存原 null。|
|AC-003|folder_stats 未知计数及账号/分组聚合 known_unread_count；搜索/常规列表传播未知且保留总数。|
|AC-004|`test_legacy_migration.py` 持久化原 read/attachment 并断言不存在 flag 为 NULL，源库只读未变。|
|AC-005|`test_migration_validation.py` 0018 升级保留原值、catalog nullable/default 与 NULL 降级拒绝；OpenAPI 漂移检查通过。|

### 结果摘要

- 修复提交：`300d394`、`f5ef673`。
- 未知 read/flag/attachment 贯穿存储、查询、API 与前端；未读统计传播未知，旧库无 flag 来源保存 null。未批量改写历史数据。
- 最终 PG 全量：477 passed / 0 skipped；不变更脚本状态。

## 最终全量验证说明

- 真实 IMAP 与 PostgreSQL 全量串行运行：477 passed / 0 skipped，只有既有 Starlette 弃用警告；运行 `e9e0192dae624ce980a1ae3ee8fe66b3`，正常清理本轮测试库。
- 首轮两个旧夹具失败已补明确输入并保持原预期。第二轮与 IMAP 定向并行共用测试邮箱，目标邮件被另一套件清理；停止并行后最终全量通过。未因环境失败修改生产行为。
- 未部署生产，未改写运行容器数据。
