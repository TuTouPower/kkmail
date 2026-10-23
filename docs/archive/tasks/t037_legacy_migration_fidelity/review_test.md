# Task review t037（reviewer_focus: 测试）

- task：`t037_legacy_migration_fidelity`
- spec：`docs/tasks/t037_legacy_migration_fidelity/spec.md`
- diff_anchor：`22a3f23c48fa7e66daff400ca6f2db3c7cfd0c19`
- target：`git -C '[REDACTED_LOCAL_PATH]' diff 22a3f23c48fa7e66daff400ca6f2db3c7cfd0c19`
- round：1
- reviewed_at：2026-10-23T17:32:12+08:00

## Round 1 (2026-10-23T17:32:12+08:00)

reviewed_scope: 8e08dcaccd6fbe49

### Findings

#### t037_test_f001 - 测试未覆盖 Python 超长整数转换失败

- 严重度：minor
- 锚点：AC-003、AC-004。超范围 provider UID 应作为未知 UID 保留邮件，而不能令 importer 整批失败。
- 位置：`tests/mail_core/test_legacy_migration.py:192-204`
- 问题：fixture 覆盖 `9223372036854775808`（超过 PostgreSQL BIGINT 上限），但没有覆盖超过 Python 3.14 默认 4300 位转换上限的十进制文本。当前 `_legacy_uid` 对这种输入抛出 `ValueError`，fixture 不会捕获该失败。
- 建议：增加 5000 位十进制 UID 源行，断言邮件仍被迁移且 `MessageLocation.uid` 为 null。

#### t037_test_f002 - 未覆盖空字符串 subject 与 sender

- 严重度：minor
- 锚点：AC-001。AC 同时要求缺失值和空值写为空事实值。
- 位置：`tests/mail_core/test_legacy_migration.py:62-74`
- 问题：fixture 对 subject/sender 只提供 SQL NULL；没有 `subject=''` 或 `sender=''` 样本。若实现将空串与缺失值区别处理，现有断言仍可能通过。
- 建议：增加 subject/sender 为空字符串的源记录，并断言持久化事实值为空，不出现展示占位文本。

### 结论

- 改测方向复核：本轮既有测试改动仅更新新增 Alembic head 并添加断言，没有删除旧测试、弱化旧断言、增加 skip/only 或复制生产逻辑冒充覆盖。
- 测试可信：legacy fixture 以只读 SQLite 连接调用生产 importer helper，写入真实 PostgreSQL Session 后逐字段读取；重跑验证不覆盖已有内容，源文件 SHA-256 前后比对。Archive、API、migration、remote-push 与 frontend 测试均触达各自生产路径。Reader unknown archive-state 用例隔离 provider 构建边界但保留实际 `run_archive_batch`。
- AC 覆盖：当前测试覆盖 AC-001~008；两个待补用例均为明确输入边界的 minor 覆盖缺口，不构成某条 AC 完全无测试。
- 本轮新发现：2 条 minor。
- 未进表的提示：完整 PostgreSQL 测试未由 reviewer 执行，遵守“不要运行会修改数据库/业务数据的测试”指令；本报告依据源码与测试断言核查。
- 总体判断：测试直接触达 importer、数据库 migration/query/API、provider callsite guards 与 Reader；仅有两项非阻塞边界测试缺口。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：`re_verified`。检查真实 importer 测试对 SQL NULL 与旧占位字面值的持久化断言；空字符串分支缺少独立样本，见 f002。
- AC-002：`re_verified`。检查 To 多地址、Cc 独立地址、text/html/未知 body_type 的逐字段持久化断言。
- AC-003：`re_verified`。检查 Graph 有效/缺失/非法/无时区日期、IMAP/sequence/empty/unknown 模式、有效/无效 UID 断言；另检查 signed BIGINT 上界与超界行为，发现 Python 超长数字转换缺口，见 f001。
- AC-004：`re_verified`。检查 fixture 使用临时 SQLite 文件、生产 importer helper、真实 PG Session、重跑幂等断言与源文件 hash 比对；未运行数据库测试。
- AC-005：`re_verified`。检查 detail/sync-body API null、OpenAPI null 分支、TS mapper null/缺失值和 Reader `null` 状态不触发 sync 的断言。
- AC-006：`re_verified`。检查原始 Graph ID、空/空白 ID、其他模式 ID、UUID5 local key、UID 来源和 null-ID 调用边界的生产逻辑断言。
- AC-007：`re_verified`。检查真实 Alembic migration 测试既有 ID 保留、多个 null 允许持久化、downgrade fail-closed 与 row/head 保留断言。
- AC-008：`re_verified`。检查 read/flag 本地更新且不建 remote op/job，trash/sync-body 409，archive/reconcile/remote-push 不传 null provider ID 的相关断言。
- 覆盖率：`coverage = 8 / 8`

verdict: PASS

## Round 2 (2026-10-23T17:38:11+08:00)

reviewed_scope: e7d935c32ba1685d

### Round 1 finding closure

- `t037_test_f001`：已修。SQLite fixture 新增 5000 位 UID 行 38；真实持久化断言确认整批仍导入，uid 为 null（`tests/mail_core/test_legacy_migration.py:335-347, 480-494`）。
- `t037_test_f002`：已修。fixture 行 37 同时提供空 subject/sender，并从 PostgreSQL 读取断言空 subject、空 from_address、null from_name，无展示占位（`tests/mail_core/test_legacy_migration.py:322-334, 531-547`）。
- 本轮新测试 finding：0。

### 最终 scope 与测试可信度

- Legacy importer fixture 使用生产 `migrate_retained_messages`、只读 SQLite 文件和真实 PostgreSQL Session；持久化后逐字段断言，重跑确认不覆盖已有记录，文件 SHA-256 前后相同（`tests/mail_core/test_legacy_migration.py:355-389, 390-594`）。UID 样本覆盖缺失/非法、0、负数、signed BIGINT 最大值、最大值 + 1 与 5000 位值；Graph 日期覆盖有效、missing、invalid、naive、空/空白 ID 独立组合；模式覆盖 uid、imap、sequence、empty、unknown。正文覆盖 text/html/缺失 body_type；地址覆盖多 To/Cc 与空/字面 sender。
- AC-005 用例让真实 `run_archive_batch` 执行，只 spy `build_provider`；断言缺少 archive state 时详情和 sync-body 都返回 null，调用后仍无状态行/worker job/provider 调用（`tests/mail_core/test_message_detail_api.py:108-149`）。前端 mapper 单测覆盖显式 null 与缺失字段；Reader 测试覆盖 archived true/false/null 下空正文及 HTML preview 隔离（`src/frontend/src/api/mailCore.test.ts:85-110`; `src/frontend/src/components/MessageReader.test.tsx:276-296`）。
- AC-006..008 的测试分别触达 archive claim、reconcile 输入、remote push、local-only mutations 与 API 409；migration 测试在 PostgreSQL 验证 nullable 列、已知 ID 保留、多个 null 可存储、downgrade fail-closed 且失败后行与 revision 保留（`tests/mail_core/test_archive_scheduler.py:28-58`; `tests/mail_core/test_remote_ops_reconcile.py:136-205`; `tests/mail_core/test_message_mutations_api.py:157-191`; `tests/mail_core/test_migration_validation.py:134-228`）。
- Shared AC-013..014 的现有测试仍覆盖 IMAP INTERNALDATE 与 MIME Date 分离、Gmail/Graph 错误时间拒绝、归档 MIME Date 不覆盖 provider 时间、API/OpenAPI null、ASC/DESC 空日期 keyset 跨页无漏项/重复（`tests/mail_core/test_imap_header_decode.py:25-78`; `tests/mail_core/test_gmail_graph_contracts.py:598-655`; `tests/mail_core/test_blob_archive_fixes.py:439-573`; `tests/mail_core/test_folder_role_inbox_api.py:110-139`; `tests/mail_core/test_keyset_pagination.py:133-178`; `tests/mail_core/test_openapi_contract.py:74-84`）。
- 未见删减旧语义测试、skip/only、复制生产逻辑替代真实路径，或削弱此前 nullable time/migration 断言。Final scope 中生产实现未在 reported test runs 后另行变更的状态由父任务/实现侧确认；reviewer 本轮独立检查源码与测试 diff，遵照要求未执行会改数据库的套件。
- 实现侧报告：focused importer PostgreSQL 1 passed / 452 deselected / 1 warning；importer+detail 2 passed；完整后端 453 passed / 1 warning；前端 API/Reader 31 passed。以上为实现侧执行记录，本 reviewer 未重跑 DB 测试。

### 结论

- 前轮 finding 复核：2 条 minor 均已修。
- 本轮新发现：0。
- AC 覆盖率：AC-001..008 = 8 / 8；shared AC-013..022 = 10 / 10。

verdict: PASS
