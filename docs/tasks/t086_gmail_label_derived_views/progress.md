---
tid: "t086"
slug: "gmail_label_derived_views"
title: "Gmail 虚拟标签改为派生视图并根治重复拉取与空壳导航"
status: "done"
branch: "t086_gmail_label_derived_views"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "82b86fb716e34a0fe71bbc317bad75ac212f21e5"
spec_source_sha: "82b86fb716e34a0fe71bbc317bad75ac212f21e5"
depends_on: ""
conflicts_with: ""
note: "来源 p086（supersede t084）：标签成员关系由常规 FETCH 摄取并投影为视图，废除 paused 虚拟同步单元"
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 领域层新增 `folder_views.py`：`container` / `view` 二分与 `is_gmail_view` / `is_syncable_folder` 单一判定；`folders.kind` 由迁移 `20261123_0004` 回填，虚拟标签重置为 `idle`，不再 `paused`。
- IMAP 常规 FETCH 在 `X-GM-EXT-1` capability 存在时增补 `X-GM-LABELS`，解析为 `RemoteMessageMeta.labels`；`apply_metadata_page` 把 `\Important` 成员落为指向 view folder 的 `message_locations`，零额外往返、零重复下载。
- 查询层 `view_scope_folder_ids` / `view_stats` 把 All Mail 投影为全部非垃圾/废纸篓物理目录、Important 投影为标签 location；folder-stats 返回真实计数，`unified_inbox` 展开视图作用域并复用 keyset 去重。
- 同步引擎、delta、reconcile、patrol、idle watcher、mutations、worker 与同步请求解析统一用 `kind==container` 排除视图，view 不再产生任何作业；前端侧栏 fixture 改为真实计数并断言不再出现 `-`。
- 旧语义测试 `test_a321_gmail_virtual_exact.py` 与 t056 的 paused AC 因语义作废被删除（非改预期），由 `test_gmail_label_views_discovery.py` / `test_imap_gm_labels.py` / `test_gmail_label_views.py` 覆盖新语义；两处硬编码 Alembic head 改为读取 `CURRENT_HEAD_REVISION`。
- 撤销 `[deploy]` AC-010：需真实 Gmail 账号与外网，无法在此环境诚实打勾；机制由 IMAP stub + PG 集成覆盖。
- 修复与 t086 无关的既存测试基建缺陷：t079 `basetemp`/`TMPDIR` 位于仓内使“仓外软链”假失败，改用 `Path.home()` 下临时目录。
- 文档更正：`p060` 失效路径勘误、blueprint（architecture/domain/conventions）与决策记录 `20261123_gmail_label_derived_views.md` 已更新。`t056/task.md` 的风险段原计划同步更正，但 `finish` 禁止跨 task 修改核心资产，已撤回该改动；更正结论以本条与决策记录为准（AC-008 相应收敛）。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-23T12:30:00+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t086_code_f001|important|已修|迁移改为仅对 Gmail 账号回填 view，非 Gmail all/important 仍为 container|src/mail_core/db/alembic/versions/20261123_0004_gmail_label_views.py:36|
|t086_code_f002|minor|遗留|历史 Important 成员需一次性标签回填作业，常规同步会逐步收敛|p089|
|t086_test_f001|important|已修|新增 PG 用例覆盖迁移 Gmail 过滤、幂等与 messages 总数不变|tests/mail_core/test_gmail_label_views.py:122|
|t086_test_f002|minor|已修|新增不显式传 label_view_folders 的派生映射用例|tests/mail_core/test_gmail_label_views.py:166|
|t086_test_f003|minor|已修|新增空账号视图 0 计数断言|tests/mail_core/test_gmail_label_views.py:200|
|t086_test_f004|minor|撤回|迁移用例断言 messages 前后计数相等，迁移若插入行即失败；精确“2 物理+1 标签=3 locations”已由 `test_label_membership_becomes_location_and_views_return_real_counts` 覆盖，无需重复 seed|tests/mail_core/test_gmail_label_views.py:91|

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足
- 测试：`scripts/run-mail-core-tests.sh unit` 1686 passed、540 skipped；`scripts/run-mail-core-tests.sh run --no-cov` 2224 passed、2 skipped（含迁移单 head 与新增视图 PG 用例）；前端 `npm test`/`tsc -b`/`build`、`npm --prefix src/desktop test`、敏感文档扫描全通过
- 黑盒：`npm --prefix src/frontend run test:e2e` 23 passed
- review：待 reviewer 填写
- AC 判定：见 `task.md` 行内打勾（AC-001~009 已勾选，待独立复核）

### 结果摘要

- 虚拟标签从 paused 空壳改为派生视图；重复拉取、空壳导航、错误码与未知角标在同一根因下消除。

### 长期文档闭环

在 active spec 的 front matter `tasks` 清单中登记当前 tid（`task.py specs list --json`）；无长期 spec 变更时写 `- specs_index: not_applicable: 具体原因`。正式 spike 须有 report、现存 finding、采纳结论、后续 tid 或无需后续理由；finish 会检查这些引用。

- specs_index: docs/specs/mail_sync_and_storage.md # tasks 增加 t086
