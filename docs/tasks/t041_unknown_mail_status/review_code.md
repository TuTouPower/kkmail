# Task review t041（reviewer_focus: 代码）

- 实际审查基线：`3cedba683fd941565ac42a1a2d38e11a33a8eee3`。
- 审查方式：独立读取当前工作区完整实现、相关测试断言及文档；未修改生产代码，未重跑数据库测试。
- reviewed_at：2026-10-23T19:15:21+08:00
- 流程限制：用户授权直接 main 实施，task front matter 的 diff_anchor 为空；现工具只能在 start worktree 时赋值，因此无法渲染正式 prompt。本报告按 code/shared prompt 规则人工审查，以真实基线计算 reviewed_scope，不伪造 active/done 或工作区身份；不声称通过 task-work 状态门禁。

## Round 1 (2026-10-23T19:15:21+08:00)

reviewed_scope: 0ce332858936ab81

### Findings

零新增 finding。

### 复核结果

- 先前发现的搜索未知读数已修：`MessageList.tsx` 搜索结果存在 null 读状态时传播未知，不再显示确定 0 或部分和；已有过滤、样式及打开时自动标已读仅匹配明确 false。
- 先前发现的旧 item 回滚已修：`queries.ts` 在乐观更新前优先捕获缓存原始读状态，失败恢复该值；null 不再回退成传入旧 false。旗标同样优先缓存且保留 null。
- Message 三状态与 FolderStats.unread_count 无 false/0 默认；0019 不改写已有记录，降级前检查 NULL 并拒绝无法表达的值。API、OpenAPI 与 TS 契约保持 nullable。
- 统计 SQL 同时计算 folder_count 与 known_unread_count，防止 SUM 自动忽略 NULL 后呈现部分和；total_count 独立判断可知性。空文件夹重算仍得到真实 0。
- 旧库读/附件列原值保留，缺失旗标写 null；不依据无法辨识的历史默认值重写数据。

### AC 复验方式

- AC-001：re_verified。核对 models、metadata.upsert 的未知跳过路径与 test_unknown_mail_status 首次插入/已知后更新断言。
- AC-002：re_verified。核对 API DTO、mapper 透传、列表明确 false 分支、Reader mixed 旗标，以及缓存 null 失败恢复代码和回归测试。
- AC-003：re_verified。核对 folder_stats 未知计数、账号/分组聚合 known_unread_count、搜索及常规列表显示分支。
- AC-004：re_verified。核对 migrate_retained_messages 的 bool 源列迁移与 is_flagged=None，以及只读源库测试新增持久化断言。
- AC-005：re_verified。核对 0019 upgrade/downgrade 与真实迁移用例中既有值保留、NULL 降级拒绝和再次升级断言；核对生成契约 nullable 变更。
- coverage = 5 / 5

### 结论

- 正确性、安全、公开契约、性能、模块职责、异常处理及文档一致性均已扫描；未发现新增阻断。
- 规模提示：MessageList.tsx 713 行，test_migration_validation.py 710 行；生成的 OpenAPI/TS schema 不计规模。此处只作维护提示，不扩展本轮重构范围。
- 验证限制：本报告独立复核代码及断言，运行结果由实施侧门禁报告提供；不宣称 reviewer 已运行全量测试或生产部署。
- 系统性 follow-up：direct-main 与任务工具状态入口不匹配，已向主代理报告；不阻断当前实现正确性。

verdict: PASS

## Round 2 (2026-10-23T19:19:22+08:00)

### Findings

#### t041_code_f001 - IMAP 扩展旗标被误判为系统旗标

- 严重度：important
- 锚点：AC-001、AC-002；外部实际返回的 flag 必须按完整 token 判断，不把其他旗标转换为确定 read/flag 状态。
- 位置：`src/mail_core/providers/imap.py:227`，`tests/mail_core/test_imap_unknown_flags.py:8`。
- 问题：`_parse_fetch_flags` 使用子串匹配。独立调用 `_parse_fetch_flags(r"1 (UID 1 FLAGS (\SeenLater \FlaggedElse))")` 返回 `(True, True)`，虽然响应没有独立的 `\Seen`、`\Flagged` token。新测试 raw bytes 字面量使用双反斜杠，也未覆盖标准单反斜杠 token 的精确性。
- 建议：将 FLAGS 内容按空白拆分为大小写归一 token 集合，再做完整成员匹配；测试使用标准单反斜杠，并覆盖前缀扩展旗标及大小写。

### 复核与结论

- 缺 FLAGS 返回 None/None、metadata 保留未知、delta 不生成 false patch 的分支正确；显式空 FLAGS() 仍正确返回 false/false。
- 独立执行新增 helper 复现前缀误判；未修改代码或测试。
- AC-001/002 对新增 IMAP flag 输入边界尚未满足，其余前轮结论保持。

verdict: FAIL

## Round 3 (2026-10-23T19:20:10+08:00)

### 前轮 finding 复核

- `t041_code_f001`：代码缺陷已消除。`_parse_fetch_flags` 先 `casefold().split()` 构造完整 token 集合，随后判断 `\seen`、`\flagged` 的成员关系；不再对子串匹配。metadata 与 delta 调用同一 helper。
- reviewer 独立执行四类输入：前缀扩展旗标返回 false/false；混合大小写系统旗标返回 true/true；缺少 FLAGS 返回 None/None；空 FLAGS() 返回 false/false，四项断言通过。
- 新测试字面量已按 AST 实际 bytes 核对：系统旗标前仅一个 `0x5c`，是标准单反斜杠；metadata 与 delta 均增加前缀扩展旗标和混合大小写断言。旧报头 fixture 仅修正协议输入，既有预期保持。

### 结论

- 本轮新 finding：0；前轮阻断已修。
- 新增 IMAP 路径对缺省、显式空和明确状态保持区分，满足 AC-001/002；其余 AC 延续 Round 1 核对结论。
- 复验边界：独立运行真实 parser helper 的四项断言，未重跑 PostgreSQL 或真实 IMAP 集成；不将实施侧套件结果称为 reviewer 实测。
- 按主代理要求，本次是 direct-main 增量人工复核，不重算任务工具 scope 或伪造 front matter。

verdict: PASS
