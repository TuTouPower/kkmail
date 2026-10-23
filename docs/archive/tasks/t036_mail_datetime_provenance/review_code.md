# Task review t036（reviewer_focus: 代码）

- task：`t036_mail_datetime_provenance`
- spec：`docs/tasks/t036_mail_datetime_provenance/spec.md`
- diff_anchor：`ce342a38d6950fe08fd985262f0735f898b2b042`
- target：`git -C '/Users/karson/kar/code/kkmail_t036' diff ce342a38d6950fe08fd985262f0735f898b2b042`
- round：1
- reviewed_at：2026-10-23T09:31:53+08:00

## Round 1 (2026-10-23T09:31:53+08:00)

reviewed_scope: 6606a8fb3c2a346a

## Findings

### t036_code_f001 - IMAP sort_time 仍取自邮件 Date 头

- 严重度：important
- 锚点：AC-001；约束“收件时间、MIME Date 与未知时间不能混用”。有效的邮件 Date 头与服务器收件时间不同时，API 仍返回发件方填写的时间。
- 位置：`src/mail_core/providers/imap.py:251`
- 问题：IMAP FETCH 只请求 `UID FLAGS BODY.PEEK[HEADER.FIELDS (... DATE ...)]`（约第 458 行），解析器再用 MIME `Date` 头生成 `sort_time`。该值由邮件内容提供，不是 IMAP 服务器返回的收件时间；因此即使缺失/非法值已改为 `null`，所有有效但与实际收件时间不一致的 Date 仍会冒充 received time，造成列表时间与排序错误。
- 建议：FETCH 请求服务器 `INTERNALDATE`，仅从该字段生成 `sort_time`；缺失或非法时保留 `null`，不回退到 MIME Date。

## 结论

- 前轮 finding 复核：首轮，无。
- 本轮新发现：1 条。
- 未进表的提示：`src/mail_core/mail/application/queries.py` 共 405 行，本 task 净增 8 行；`tests/mail_core/test_gmail_graph_contracts.py` 共 644 行，本 task 净增 47 行。按 review 规则只作规模提示。`src/mail_core/providers/imap.py` 达 800 行但本 task 未增加净行数，不触发文件规模 finding。
- 已检查正确性、契约、性能、架构、安全、健壮性与文档一致性；除上述 IMAP 时间来源问题外，未发现需登记的问题。

### AC 复验方式

- AC-001：`re_verified`。独立检查 IMAP/Gmail/Graph 解析及 metadata upsert；定向运行 IMAP/Gmail/Graph 时间解析用例，9 passed。复验确认缺失/非法值不造当前时间、Graph 不回退 lastModified，但发现 IMAP 有效时间仍取自 MIME Date。
- AC-002：`re_verified`。检查归档回填只更新缺失主题/发件人，未再写入 sort_time；检查对应归档测试断言覆盖相异 MIME Date 与已有/未知时间。
- AC-003：`re_verified`。检查 nullable model/migration/API、ASC/DESC `NULLS LAST` 与两段式 NULL cursor 条件、前端 null 日期显示；检查 PostgreSQL keyset 与迁移测试断言。未独立重跑 PostgreSQL 用例。
- AC-004：`re_verified`。检查新增自动测试断言覆盖 IMAP/Gmail/Graph 有效、缺失、非法时间，归档 MIME Date 保护及 NULL 跨页；parser 定向用例已运行，迁移/keyset/归档 PostgreSQL 用例未重跑。
- 覆盖率：`coverage = 4 / 4`
- 总体判断：存在一条违反收件时间来源约束的 important finding，当前实现未满足 AC-001。
- 系统性 follow-up：无。

verdict: FAIL

## Round 2 (2026-10-23T09:52:50+08:00)

reviewed_scope: 88dd3196a7257c27

### Findings

### t036_code_f002 - Gmail 将非整数类型时间强制转成有效时间

- 严重度：important
- 锚点：AC-001。provider 时间类型非法时，结果应保持未知；当前输入会落库为伪造收件时间。
- 位置：`src/mail_core/providers/gmail.py:118`；`src/mail_core/providers/parsing/gmail_history.py:34`
- 问题：Gmail [Message API](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages) 将 `internalDate` 定义为 string（int64 format）。`int(sort_raw)` 会把 JSON `true` 和 `1.5` 都转成 `1`，两条解析路径于是返回 `1970-01-01T00:00:00.001Z`，而不是 `null`。已用 Python 3.14 直接调用两条解析路径复现。
- 建议：在转换前校验 provider 值类型与整数形式，拒绝布尔值和非整数数值，非法值继续保留 `null`。

### t036_code_f003 - Graph 无时区时间被擅自解释为 UTC

- 严重度：important
- 锚点：AC-001。无法按 provider 时间契约解析的值必须保持未知。
- 位置：`src/mail_core/providers/parsing/graph_delta.py:19`
- 问题：Graph [message resource](https://learn.microsoft.com/en-us/graph/api/resources/message?view=graph-rest-1.0) 将 `receivedDateTime` 定义为 DateTimeOffset 且使用 UTC；当前代码接受无 offset 的 ISO 日期并附加 UTC。例如 `2026-10-20T12:30:00` 被存成 `2026-10-20T12:30:00Z`，为缺失时区的数据补造了时间语义。已用 Python 3.14 直接调用 `_parse_dt` 复现。
- 建议：缺少时区 offset 时返回 `None`；保留 provider 明确给出的有效 offset。

## 结论

- 前轮 finding 复核：`t036_code_f001` 已消除。IMAP FETCH 请求 `INTERNALDATE`，解析只读取该字段；MIME `Date` 不再进入 metadata，缺失/非法值为 `None`。
- 本轮新发现：2 条 important，均违反 AC-001。
- 未进表的提示：`src/mail_core/mail/application/queries.py` 共 405 行，本 task 净增 8 行；`tests/mail_core/test_gmail_graph_contracts.py` 共 644 行，本 task 净增 47 行，按文件规模规则只作提示。`src/mail_core/providers/imap.py` 共 799 行且本 task 净减 1 行，不触发规模 finding。未发现新增高圈复杂度函数。
- 总体判断：IMAP 来源修复通过；Gmail 与 Graph 仍会将无效时间编码成具体时间，AC-001 尚未满足。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：`re_verified`。独立运行 IMAP/Gmail/Graph parser 测试，33 passed、1 skipped；另直接复现 Gmail 布尔/浮点时间及 Graph 缺时区时间被转换为具体时间，形成 f002/f003。
- AC-002：`re_verified`。检查 `archive.py` 已移除 MIME `Date` 对 `sort_time` 的赋值，并检查归档测试覆盖已有时间保留及空主题回填；本轮未运行 PostgreSQL 归档测试。
- AC-003：`re_verified`。检查 nullable migration、API/OpenAPI 类型、ASC/DESC `NULLS LAST`、nullable cursor 条件及前端 null 日期显示；检查分页测试断言。本轮未运行 PostgreSQL migration/keyset 测试。
- AC-004：`re_verified`。parser 测试已运行；检查归档与 nullable keyset 的自动测试断言覆盖 MIME Date、未知时间和双向跨页。
- 覆盖率：`coverage = 4 / 4`
- 已检查正确性、契约与 breaking change、性能、安全、架构可维护性、健壮性和文档一致性。

verdict: FAIL

## Round 3 (2026-10-23T10:36:44+08:00)

reviewed_scope: 87bdfa30d5113c56

### Findings

无。

### 结论

- 前轮 finding 复核：`t036_code_f001` 已由 IMAP `INTERNALDATE` 解析消除；`t036_code_f002` 已由 Gmail 共用的整数时间解析器消除；`t036_code_f003` 已由 Graph 拒绝无 offset 值消除。
- 本轮新发现：0 条。复核 attempt 2 相对 `e0d4f0c676c50fd0dc4e7a54b99ca5baaf858703` 的完整最终 scope；补测后的 unstaged 改动仅涉及两个测试文件，未改动生产实现。
- 代码核查：provider 缺失时间保持 null，upsert 保留已有时间；migration `0017` 不改写历史值，含 NULL 时拒绝 downgrade；API/OpenAPI、双向 NULLS LAST 与 nullable keyset、前端 null 显示及归档 MIME Date 保护均与 spec 一致。
- AC 复验方式：AC-001 检查 IMAP/Gmail/Graph parser 和测试；AC-002 检查 archive 回填逻辑及对应测试；AC-003 检查 migration、API、查询、cursor 与前端测试；AC-004 检查新增测试均触达生产 parser、archive、migration、query 或 API 路径。上述四项均为 `re_verified`。
- 完整后端套件：443 passed / 1 warning（实施方本轮运行结果；reviewer 未重跑）。定向 parser 测试前轮已运行通过。
- 覆盖率：`coverage = 4 / 4`。
- 未进表的提示：无新增复杂度或文件规模提示；未发现安全、性能、健壮性、架构或文档一致性问题。
- 总体判断：attempt 2 当前源码满足 AC-001~004；无未解决 finding。
- 系统性 follow-up：无。

verdict: PASS
