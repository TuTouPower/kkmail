---
tid: "t036"
slug: "mail_datetime_provenance"
title: "保持邮件时间来源准确并避免缺失值漂移"
status: "done"
branch: "t036_mail_datetime_provenance"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "e0d4f0c676c50fd0dc4e7a54b99ca5baaf858703"
depends_on: "t035"
conflicts_with: ""
note: "来源：审查确认 IMAP/Gmail/Graph 时间缺失时填当前时间，归档还会用 MIME Date 覆盖 received time。; 时间文件与 t035 provider 元数据实现重叠，必须先合 t035 再开始。; rewound: effective=active -> backlog（main 记录为 backlog）; attempt1 diff_anchor 早于 t032 已合入的 migration 0016；按 first-parent 契约停止旧分支并从新 main 重开，完整补丁与复审报告已备份到 .scratch/t036_attempt1_backup。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

### Attempt 1 记录（diff_anchor `ce342a38d6950fe08fd985262f0735f898b2b042`）

- 将 IMAP/Gmail/Graph 缺失或非法时间保留为 `null`；IMAP 仅用 FETCH `INTERNALDATE`，不使用 MIME `Date`；Graph 只采用 `receivedDateTime`。provider 后续缺时间时保留已有收件时间。
- Gmail 两条解析路径共用 `internalDate` 解析器，只接受整数类型或整数格式字符串，拒绝布尔值、浮点数与非法格式；Graph `receivedDateTime` 必须含显式时区，保留服务商给定 offset。
- 增加 `messages.sort_time` nullable migration；不改写任何历史时间。旧 schema 有 NULL 数据时 downgrade 直接拒绝，避免伪造回填值。
- API/OpenAPI、查询 DTO、前端日期类型与显示同步支持 null。ASC/DESC 显式 `NULLS LAST`；游标兼容旧 ISO 时间 token，并支持 NULL 组按 ID 稳定翻页。
- MIME Date 不再回填收件时间；归档 header 回填只更新各自缺失的主题/发件人字段。thread 排序与归档优先级接受未知时间。
- 按 TDD 替换过时断言：删除 `test_archive_batch_backfills_missing_metadata_from_mime`（旧断言把 MIME Date 写入 provider received time），新增独立归档契约测试；删除 `test_decode_rejects_partial_and_malformed` 中将 `|uuid` 视为非法的旧语义，新增 nullable cursor round-trip 与独立 malformed cursor 测试；删除两个把 0015 固定为当前 head 的迁移测试，新增当前 head 与安全回滚测试；移除以 MIME `Date` 作为 IMAP received time 的旧测试，新增分歧、缺失、非法 `INTERNALDATE` 与 FETCH 请求断言。
- PostgreSQL 16.15 spike 核验：ASC 与 DESC 均显式 `NULLS LAST`。keyset cursor 为 `(sort_time: datetime | null, message_id)`；已知时间 cursor 的后续条件纳入 NULL 组，NULL cursor 只在 NULL 组按 ID 继续。证据由 `test_nullable_sort_time_pages_with_unknown_dates_last` 与 Round 1 PostgreSQL 复验支撑。
- Round 1 migration 保留时间 finding 由独立 PostgreSQL 测试处理：在 0015 写入固定时间，升级到 head 后比较原值；旧 migration 断言保持原样。
- Round 1 code/test 三项 finding 已修；Round 2 code 新发现 Gmail bool/float 时间与 Graph 无 offset 时间两项 important，已修复。Round 1/2 报告已从备份恢复，待新基线复审。

### Attempt 2（diff_anchor `e0d4f0c676c50fd0dc4e7a54b99ca5baaf858703`）

- 从主仓 `.scratch/t036_attempt1_backup/attempt1.patch` 恢复实现与测试，保留本 attempt 的 task front matter。
- t032 已占 migration `20261023_0016`。已将 t036 nullable `sort_time` migration 调整为 `20261023_0017`，父 revision 指向 `20261023_0016`。
- 处理 `tests/mail_core/test_migration_validation.py` 三方冲突：保留 t027 ordering migration 独立升降级测试；另保留 t036 nullable migration 当前 head、NULL 降级拒绝与前序 revision 测试；后端 migration head 断言更新为 0017。
- 补齐 Round 2 复核要求：Graph `receivedDateTime` 对 bool、数字、对象输入返回 null；归档空主题回填时，provider `sort_time=null` 不被 MIME Date 补造。
- 定向后端：parser/OpenAPI 41 passed、1 skipped；nullable migration/keyset 真实 PostgreSQL 13 passed；补充 Graph 和归档用例分别 8 passed、1 passed。
- 完整后端 `scripts/run-mail-core-tests.sh run`：443 passed / 1 warning，373.07 秒。
- 前端 `npm test`：254 passed（39 files）；`npx tsc -b`、`npm run build`、`npm run lint`、`npm run openapi:check`、`python scripts/export_openapi.py --check` 均通过。
- 黑盒：`npm run test:e2e` 13 passed；`scripts/run_full_stack_e2e.py` 8 passed，测试库自动清理。
- 其他门禁：模板 contract 149 passed；desktop `npm test` 通过；`npm run test:packaged` 验证 SPA、PostgreSQL 二进制架构及初始化/启动/停止/重启持久状态通过。
- 收尾 `git diff --check`、`md_format.py --changed --check` 与 `task.py preflight t036 --require-verified` 均通过；preflight 保留 1 条已核对的范围提示，32 个被规则识别为无关路径包含本 task 的 API/OpenAPI、日期类型与阅读器联动文件。
- packaged smoke 前后核对主仓 `vendor/pgsql` 360 个文件 SHA-256 全一致；临时 symlink、release、前端 dist 与本轮 E2E 产物已清理，主仓工作树 clean。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1（attempt 1，2026-10-23T09:37:31+08:00）

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t036_code_f001|important|已修|IMAP 收件时间改由 FETCH `INTERNALDATE` 唯一提供，MIME `Date` 不再进入解析路径；缺失/非法时保留 null。|`src/mail_core/providers/imap.py`；`tests/mail_core/test_imap_header_decode.py`|
|t036_test_f001|important|已修|OpenAPI 测试现对 `MessageOut.sort_time` 与 `MessageDetailOut.date` 分别断言 anyOf 含 null 类型分支。|`tests/mail_core/test_openapi_contract.py`|
|t036_test_f002|minor|已修|新增独立真实 PostgreSQL 迁移测试，验证既有收件时间升级后精确保留；未就地改旧迁移预期。|`tests/mail_core/test_migration_validation.py`|

### Round 2（attempt 1，2026-10-23T09:52:50+08:00 code / 09:52:02+08:00 test）

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t036_code_f002|important|已修|Gmail received time 解析统一校验整数类型与整数文本格式，拒绝 bool/float，避免将不同 JSON 类型强制转换为 1ms。|`src/mail_core/providers/parsing/gmail_history.py`；`src/mail_core/providers/gmail.py`；`tests/mail_core/test_gmail_graph_contracts.py`|
|t036_code_f003|important|已修|Graph 无 offset 的 `receivedDateTime` 返回 null；显式 offset 原样保留。|`src/mail_core/providers/parsing/graph_delta.py`；`tests/mail_core/test_gmail_graph_contracts.py`|

TEST Round 2 PASS（scope `88dd3196a7257c27`）。该报告来自 attempt 1； attempt 2 base 与代码范围变更后须重新评审。

### Round 3（attempt 2，2026-10-23T10:36:44+08:00）

- 最终 scope：`87bdfa30d5113c56`；`check_review_status.py` 输出 `overall=PASS`、`review_scope=ok`、`round=3`。
- code 与 test 报告均 PASS；TEST 轴独立核实了补充的 Graph 非字符串输入和归档 null 时间场景。
- 新 finding：无；Round 2 历史 finding 已在前述处置表中修复。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：AC-001~004 完成；received time 只保留服务商给定值，缺失/非法值以 null 保存、返回和稳定分页；MIME Date 不覆盖或补造 received time。
- 测试：attempt 2 完整后端 443 passed / 1 warning，前端 254 passed；类型、构建、lint、OpenAPI、schema、模板 contract、desktop 单测与 packaged smoke 均通过。
- 黑盒：前端 E2E 13 passed；全栈 E2E 8 passed；packaged desktop PostgreSQL 生命周期通过。
- review：attempt 2 Round 3 code/test PASS，scope `87bdfa30d5113c56`，无未解决 finding。
- AC 证据：见 `handoff.json`

### 结果摘要

- provider 时间来源、缺失值与 NULL 排序语义及 attempt 2 的 migration 链均通过项目门禁与独立复核。
