# Task review t037（reviewer_focus: 代码）

- task：`t037_legacy_migration_fidelity`
- spec：`docs/tasks/t037_legacy_migration_fidelity/spec.md`
- diff_anchor：`22a3f23c48fa7e66daff400ca6f2db3c7cfd0c19`
- target：`git -C '<local-path>' diff 22a3f23c48fa7e66daff400ca6f2db3c7cfd0c19`
- round：1
- reviewed_at：2026-10-23T17:32:12+08:00

## Round 1 (2026-10-23T17:32:12+08:00)

reviewed_scope: 8e08dcaccd6fbe49

### Findings

#### t037_code_f001 - 超长十进制 UID 会中止整批邮件导入

- 严重度：important
- 锚点：AC-003、AC-004。不能写入目标 BIGINT 的 UID 应保持未知，邮件内容仍应完成迁移。
- 位置：`scripts/migrate_from_legacy_db.py:103`
- 问题：`value.isdecimal()` 接受任意长度十进制字符串，随后直接执行 `int(value)`。Python 3.14 默认拒绝超过 4300 位的整数文本转换；`id_mode='uid'` 且 `provider_message_id='9' * 5000` 时 `_legacy_uid` 抛出 `ValueError`，异常沿 `migrate_retained_messages` 冒泡并使当前邮件事务失败，其他有效邮件也无法提交。已用项目 Python 3.14 独立复现整数转换异常。
- 建议：在转换前按 signed BIGINT 最大值的位数与字典序拒绝超范围值，或捕获 `ValueError` 并将该 UID 保持为 `None`，继续导入邮件内容。

### 结论

- 前轮 finding 复核：首轮，无。
- 本轮新发现：1 条 important。
- 未进表的提示：`scripts/migrate_from_legacy_db.py` 419 行（净增 93）、`src/mail_core/api/mail.py` 542 行（净增 12）、`src/mail_core/mail/storage/models.py` 414 行（净增 1）、`src/mail_core/sync/engine.py` 448 行（净增 6）、`src/mail_core/sync/remote_push.py` 465 行（净增 5）均超过 400 行；`src/mail_core/blobs/archive.py` 966 行（净增 2）超过 800 行；`tests/mail_core/test_migration_validation.py` 686 行（净增 105）超过 600 行。按审查规则仅作规模提示。未发现新增高圈复杂度函数；生成的 OpenAPI / TypeScript schema 不计入规模项。
- 已检查正确性、契约与 breaking change、性能、安全、架构可维护性、健壮性与文档一致性。Importer 按 `id_mode` 保留来源语义；null ID 的 provider 消费边界有对应护栏；nullable migration 不改写既有值且对含 null 的 downgrade 失败关闭。未发现其他本轮代码 finding。
- 总体判断：AC-003/004 的 oversized UID 输入会中止迁移，当前实现仍有未解决 important finding。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：`re_verified`。检查 importer 对空 subject/sender 写空事实值，对非空旧字面值不做 sentinel 字符串清洗。
- AC-002：`re_verified`。检查 `_legacy_sender` / `_legacy_addresses` 使用标准地址解析器，`body_type == 'html'` 才写入 HTML 列；其他类型写纯文本列。
- AC-003：`re_verified`。检查 received time 仅允许带时区 Graph 日期，UID 仅来自 `id_mode=uid` 并受 BIGINT 范围限制。发现整数转换范围检查前的 Python 位数限制缺口，见 f001。
- AC-004：`re_verified`。检查合成 SQLite fixture 通过生产 `migrate_retained_messages` 及真实 PostgreSQL Session 持久化，核对幂等查询和只读源 hash 断言；未运行会改数据库的测试。
- AC-005：`re_verified`。检查 API 详情/同步接口从缺失 archive state 返回 null、OpenAPI nullable 分支、前端 TS mapper 保留 null，以及 Reader 的 `is_archived === false` 条件。
- AC-006：`re_verified`。检查仅 Graph 非空 provider ID 映射 remote_id、SQLite ID 仅进入确定性本地 UUID；检查 archive、reconcile、remote push 及 API callsites 的 null-ID 防护。
- AC-007：`re_verified`。检查 migration 只改变 nullable 属性；测试插入两个 null ID、验证 downgrade 拒绝且 migration head 与行仍在，并单独验证已有 Graph remote ID 升级后不变。
- AC-008：`re_verified`。检查 local read/flag 不建 remote operation，trash / sync-body 对无 provider ID 返回 409；相关测试断言本地状态、响应和 provider 边界。
- 覆盖率：`coverage = 8 / 8`

verdict: FAIL

## Round 2 (2026-10-23T17:38:11+08:00)

reviewed_scope: e7d935c32ba1685d

### Round 1 finding closure

- `t037_code_f001`：已修。`_legacy_uid` 先去掉前导零，再用 PostgreSQL signed BIGINT 十进制长度和字典序上界检查，随后才转 `int`（`scripts/migrate_from_legacy_db.py:98-113`）。5000 位源 UID 现在返回 `None`，不会触发 Python 3.14 的整数文本长度异常，也不会中止整批导入。最终 importer/test diff 已复核。
- 本轮新代码 finding：0。

### 最终 scope 复核

- AC-001：空 subject/sender 写空事实值；已有非空旧字面值不按 sentinel 清洗（`scripts/migrate_from_legacy_db.py:155-158`）。
- AC-002：From、To、Cc 走 `email.utils` 标准地址解析；仅已存 `html` 进入 HTML 列，其余 body_type 进入纯文本列（`scripts/migrate_from_legacy_db.py:70-79, 155-183`）。
- AC-003：旧日期仅 `id_mode=graph` 且 ISO 时间带有效时区时写入；UID 仅 `id_mode=uid` 的正 ASCII 十进制 BIGINT 范围值写入。SQLite `id` 只用于确定性 UUID5 本地键（`scripts/migrate_from_legacy_db.py:82-113, 136-183`）。
- AC-004：真实 importer helper 接受只读 SQLite cursor 和 PostgreSQL Session；报告成功数、跳过重复项，按本地 UUID 和 Graph ID 双重避免重复，不覆盖已存在记录（`scripts/migrate_from_legacy_db.py:116-193`）。
- AC-005：无归档状态返回 `is_archived=None`；详情只对明确可寻址邮件排队，sync-body 对已寻址邮件运行真实归档 runner（`src/mail_core/api/mail.py:308-368, 371-435`）。前端 mapper 保留 null/缺失状态（`src/frontend/src/api/mailCore.ts:162`）。
- AC-006：仅 Graph 非空白原始 ID 写入 `remote_id`；无身份记录仍保留邮件。archive claim/worker、reconcile 收集、remote push 均拒绝 null/空白 ID（`scripts/migrate_from_legacy_db.py:136-144`; `src/mail_core/blobs/archive.py:225-237, 536-543`; `src/mail_core/sync/engine.py:424-449`; `src/mail_core/sync/remote_push.py:208-226`）。
- AC-007：ORM 与 Alembic 允许 nullable remote_id；升级不改已有值，降级遇到 NULL 先失败且不生成身份（`src/mail_core/mail/storage/models.py:149-154`; `src/mail_core/db/alembic/versions/20261023_0018_nullable_message_remote_id.py:16-40`）。
- AC-008：local-only read/flag 只更新本地数据，不建 remote operation 或 push job；trash/sync-body 在任何远端副作用前以 409 拒绝（`src/mail_core/mail/application/mutations.py:74-172, 183-207`; `src/mail_core/api/mail.py:371-380, 497-510`）。
- Shared AC-013：IMAP 使用 INTERNALDATE，Gmail 使用 internalDate，Graph 使用带时区 receivedDateTime；归档 MIME Date 不赋值给 sort_time，现有 provider 时间不会被报头覆盖（`src/mail_core/providers/imap.py:251-272`; `src/mail_core/providers/parsing/gmail_history.py:11-21`; `src/mail_core/providers/parsing/graph_delta.py:11-21`; `src/mail_core/blobs/archive.py:758-775`）。
- Shared AC-014：API 日期保持 nullable；列表排序把 null 放末尾，ASC/DESC cursor 对已知/未知时间均以时间与消息 ID 继续分页（`src/mail_core/api/mail.py:62-64, 124-126`; `src/mail_core/mail/application/queries.py:178-234`）。
- Shared AC-015..022：分别由 AC-001..008 覆盖；nullable API/OpenAPI/TS 与 reader 保留归档未知状态，远端身份消费者保持 null guard。
- 最终 diff 内新增/修改的实现与规范文件已纳入本轮 fingerprint；只读 reviewer 未运行数据库写入测试。实现侧记录 focused importer PostgreSQL 1 passed、importer+detail 2 passed、后端 453 passed/1 warning、前端 API/Reader 31 passed；测试证据及 reviewer 未重跑说明见 `review_test.md`。
- 未发现其他行为缺陷或超出本 task 的生产改动。代码规模提示同 Round 1；本轮无新增超限文件或复杂度风险。

### 结论

- 前轮 finding 复核：1 条 important 已修。
- 本轮新发现：0。
- 覆盖率：AC-001..008 = 8 / 8；shared AC-013..022 = 10 / 10。

verdict: PASS
