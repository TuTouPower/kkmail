# Intensive Review — 视角 7：测试与规格

- Target：当前全库，非 diff；`daca631aec54c30ce02cdb5e6499ae196dc3a72d`。
- 范围：`bundle.json` 中生产实现及关联测试；补充检索 `tests/`、`frontend/src/**/*test*`、`desktop/*test.js` 全部测试清单、断言、mock/skip。深入核对提供商协议、账户入口、同步/租约/恢复、归档/备份、API、前端传输/组件、桌面启动测试。
- Findings：Critical / High / Medium / Low / Info = 0 / 3 / 0 / 3 / 0。
- Verdict：REQUEST CHANGES。
- 限制：仅静态阅读、调用链与官方协议交叉核对；未运行 pytest、Vitest、Node 测试、构建、数据库或外部邮箱实验。不声称测试通过。未读取其他视角报告。

## Critical / High

- [High][98] tests/mail_core/test_gmail_graph_contracts.py:266 L266-L278 — **Graph 文件夹 fixture 虚构角色字段，真实 Graph 收件箱无法进入列表却有“角色映射通过”测试**。测试给响应注入 `role: inbox/archive` 与 `wellKnownName: sentitems`，再断言角色正确。Graph 官方 `mailFolder` 资源没有这两个响应属性；well-known name 是访问资源时可使用的别名。生产 `graph_folder_role()` 只依赖这两个字段，普通真实响应全部返回 `other`；`list_folders()` 将其持久化，而 inbox 查询明确只接受 `Folder.role == inbox`（`mail_core/mail/application/queries.py:168`）。因此该测试验证假协议，掩盖真实 Graph 邮箱已同步但收件箱为空。修复：用官方响应结构/录制 fixture 替换虚构属性，按 `/me/mailFolders/inbox` 等 well-known 查询返回的实际 ID 建立角色映射；补“真实结构 list_folders → sync_account_folders → metadata → inbox API”集成测试，断言 Graph 收件箱邮件可见。生产逻辑应同步修正。依据：架构 §6、§15.1 提供商 mock 与统一文件夹角色。溯源：[测试](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/tests/mail_core/test_gmail_graph_contracts.py#L266-L278)、[生产映射](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/providers/graph.py#L43-L49)、[官方资源定义](https://learn.microsoft.com/en-us/graph/api/resources/mailfolder?view=graph-rest-1.0)。`git blame`：fixture 主体来自 `d8e8fefa`，`wellKnownName` 预期来自 `9ad35eb2`；本次为全库审阅，非新增行问题。

- [High][97] tests/mail_core/test_gmail_graph_contracts.py:74 L74-L104 — **Gmail History 测试提供完整邮件，掩盖生产增量邮件元数据缺失**。测试直接在 History `message` 内填 `payload.headers`、`snippet`、完整标签，随后断言 subject；另一个 fixture L145 直接提供非邮件资源顶层 `subject`。Google 官方明确 History 响应中 message 通常只有 `id`、`threadId`。生产 `GmailProvider.delta_changes()` 原样调用 `parse_gmail_history()`，没有像初始同步那样补 `messages.get(format=metadata)`；`_minimal_meta()` 将缺失 subject/from 变为空字符串、日期变为当前时间、缺失 UNREAD 视为已读，随后 `apply_delta_page()` 写入这些值。新邮件显示空标题/空发件人及错误时间/已读状态；同一邮件跨标签重复 upsert 还可覆盖已同步元数据。L118-L122 的 `return {"page": DeltaPage(...)}` 则直接绕过解析。修复：使用只含 ID/threadId 的真实 History fixture，通过生产 provider 与 HTTP 边界 stub 验证必须发生 metadata 补全，再断言数据库/API 中标题、发件人、日期、已读字段；协议 fixture 不注入领域 `DeltaPage`。依据：架构 §7.3、§15.2 固定 Gmail History fixture，skill 视角 7“直达生产实现，不 mock 自身”。溯源：[测试](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/tests/mail_core/test_gmail_graph_contracts.py#L66-L155)、[生产入口](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/providers/gmail.py#L233-L250)、[解析器](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/providers/parsing/gmail_history.py#L11-L48)、[官方 History 响应](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.history/list)。

- [High][99] tests/mail_core/test_accounts_api_pg.py:28 L28-L54 — **账户生命周期只测 memory；真实 IMAP 添加入口从未被验证，当前 UI 无法创建可同步账户**。API lifecycle 只创建 `provider=memory`；真实 IMAP 测试 `test_imap_sync_loop.py:128` 直接调用应用函数，手动设置原始密码 CredentialStore 与 `config.imap_host`，绕过公开创建接口。实际 SPA `SettingsModal.tsx:114` 只提交 `{email, provider, credentials}`，没有 host/port/config 输入；服务将 credentials JSON 整体保存，工厂却直接把 `get_secret()` 字符串当 IMAP password，并要求 `config.imap_host`。因此按 UI 填 IMAP password JSON 可以看到“账户已添加”，同步必先失败于缺 host；即便经 API 补 host，JSON 文本也会被当成密码传给 IMAP LOGIN。修复：统一 IMAP 配置与凭据契约，补设置页填写/提交测试及“POST /api/accounts → 同步任务 → 生产 build_provider → IMAP LOGIN”边界集成测试，断言连接 host/port 和实际密码；不要直接 seed 可用账户代替该路径。依据：架构 §12 账户管理、§15 应用/API 与真实协议集成。溯源：[API 测试](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/tests/mail_core/test_accounts_api_pg.py#L28-L54)、[绕过入口的 live 测试](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/tests/mail_core/test_imap_sync_loop.py#L117-L139)、[SPA 提交](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/frontend/src/components/SettingsModal.tsx#L98-L121)、[工厂](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/providers/factory.py#L59-L74)、[JSON 持久化](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/accounts/credentials.py#L224-L225)。

## Low

- [Low][100] tests/mail_core/test_oauth_transport.py:124 L121-L133 — **Gmail 工厂接线测试用 Graph 响应断言成功**。该 Gmail 测试返回 `@odata.deltaLink/value`，只断言 `out.exhausted` 与 Bearer header。Gmail parser 对此错误 schema 返回空页，因此“完全没有解析 Gmail History”也通过该断言；当前测试没有保护 next history cursor 或邮件内容。修复：返回 Gmail `history/historyId` fixture；断言 URL host/path、History 参数、至少一条 change 和准确 `next_cursor.historyId`。若只测认证 header，改成明确命名的 transport 单元测试，并另外保留实际协议接线测试。该条单列为测试断言缺陷；不重复计算前述 Gmail 运行时故障。溯源：[完整 SHA](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/tests/mail_core/test_oauth_transport.py#L121-L133)。

- [Low][98] tests/mail_core/test_remote_ops_reconcile.py:28 L28-L40 — **reconcile 集成测试统一替换为 MemoryProvider，未覆盖 Gmail/Graph 的真实边界**。该测试正确验证 DB 删除，但工厂替换覆盖 engine/reconcile/push；仓内未见 Gmail/Graph `reconcile()` 接真实 HTTP transport 的测试。生产两个 adapter 的 reconcile 都调用自造 `RECONCILE` method，而真实 BearerTransport 会把 method/path发给 HTTP 服务，无法完成架构要求的完整扫描对账。运行时缺陷应与其他视角同根因合并；本视角仅列覆盖缺口。修复：对生产 Gmail/Graph provider 提供分页 HTTP fixtures，经 `reconcile_folder()` 执行，断言只发供应商支持的方法/端点、完整翻页后才删除消失 location，部分页/网络错误不删除。依据：架构 §6 provider.reconcile、§9 远端操作闭环、§15.1 provider mock。溯源：[测试替换](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/tests/mail_core/test_remote_ops_reconcile.py#L28-L40)、[Gmail reconcile](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/providers/gmail.py#L312-L316)、[Graph reconcile](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/providers/graph.py#L204-L208)。

- [Low][95] tests/mail_core/test_imap_provider_live.py:24 L24-L35 — **L2 真实协议测试可全部 skip，且当前 live 用例只验证发现/初次元数据**。Dovecot 不可达时该模块及 `test_imap_sync_loop.py:117` 静默 skip；`scripts/run-mail-core-tests.sh` 仅强制 DB，不要求 IMAP 可用。架构 §15.1/15.2 所列 UID 空洞、EXPUNGE、UIDVALIDITY、无 MODSEQ 降级，目前主要依赖 FakeIMAP/直接构造 MetadataPage；真实协议用例没有执行这些变化。脚本名称/成功退出不能证明 L2 通过。修复：为显式 L2 模式加入 IMAP fixture 必需检查，保留普通 L1 可跳过；补真实服务器上 append/flags/delete/reselect 的变化序列，断言生产 delta/checkpoint/本地存储结果。仅为规格覆盖缺口，无单独已证实运行时 bug，按 Low。溯源：[live skip](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/tests/mail_core/test_imap_provider_live.py#L24-L35)、[L2 脚本](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/scripts/run-mail-core-tests.sh#L20-L25)、[架构测试规格](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/docs/mail-core-architecture.md#L679-L716)。

## Spec Compliance / 已核对项

- 真实 PostgreSQL 标记、`MAIL_CORE_REQUIRE_DB=1` 与脚本缺 DB 即失败机制存在；未将所有 skip 一概视为缺陷。
- `test_sync_leases_jobs.py` 使用两个重叠数据库事务验证 SKIP LOCKED；stale fencing 测试确实调用生产 `commit_checkpoint()` 并验证拒绝。`test_chaos_lease_recovery.py` 通过回拨 lease/lock 时间模拟进程死亡，不能单独证明 OS kill 后全链路恢复，但未据此报确定 bug。
- 前端 MessageList/MessageReader 测试渲染真实组件、通过 fetch 边界替换验证 UI/请求与缓存；CSRF singleflight、401、超时、调用方 abort、乐观回滚均有对应行为断言。没有把合法 DOM 输入 helper 当伪交互问题。
- 桌面测试覆盖路径/CSP/环境清理/health 与 PostgreSQL manager；真实 PG smoke 在没有二进制时显式跳过，未假称其验证打包安装完整性。
- 备份测试明确命名为 verify drill，拒绝 stub dump 为可恢复备份；注释明确不运行 pg_restore。未把已明示范围当实现缺陷。
- 已排除产品明确限制：无发信/联系人/通知/扩展；SPA 首 100 条、缓存页未读计数、无浏览器 E2E。

## Traceability / 方法与限制

- 本报告依据 intensive-review 视角 7：外部边界 mock、生产路径可达性、真实固定协议 fixture、可观察断言、规格对照；没有证实运行时缺陷的纯覆盖缺口最高 Low。
- 静态命令包括 `rg --files`、`rg` 测试名/skip/mock/断言检索、关联生产文件阅读、`git log` 与 Graph fixture 的 `git blame`。测试与构建均未执行。
- 读取历史用于定位来源；当前任务明确全库非 diff，因此前序提交中仍存活的问题保留。未以“改动行”为过滤规则。
- 官方文档仅用于验证供应商响应结构；结论来自源码调用链，未进行真实 Gmail/Graph 网络请求。
- High 项均须在聚合阶段与契约/正确性视角按运行时同根因合并，保留此处测试证据和建议回归边界，避免重复计分。
