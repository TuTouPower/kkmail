# Task review t053（reviewer_focus: 代码）

- task：`t053_provider_account_forms`
- spec：`docs/tasks/t053_provider_account_forms/spec.md`
- diff_anchor：`e124a27a4baa5917fd39f3bb5190d54334014639`
- target：`git -C '[REDACTED_LOCAL_PATH]' diff e124a27a4baa5917fd39f3bb5190d54334014639`
- round：1
- reviewed_at：2026-10-24T14:10:51+08:00

reviewed_scope: c862c6944024541a

## Findings

### t053_code_f001 - 非字符串供应商品牌可使账户编辑返回 500

- 严重度：important
- 锚点：AC-014，非法连接配置须由 API 拒绝为脱敏字段错误。
- 位置：`src/mail_core/accounts/connection.py:35`、`src/mail_core/accounts/service.py:127`、`src/mail_core/api/accounts.py:218`。
- 问题：配置 DTO 允许任意 JSON 值；PATCH 传入 `config.provider_profile=[]` 后，在 `profile not in PROFILES` 触发 `TypeError`。编辑路由只处理 LookupError/ValueError，最终为 500，而不是字段校验失败。独立直接调用生产 `validate_connection('[REDACTED_EMAIL]', 'graph', {'provider_profile': []}, {'client_id': 'id', 'refresh_token': 'r'})` 已复现 `TypeError: cannot use 'list' as a dict key`。其他配置字段也应在使用前检查类型，避免泄露 Python 转换错误。
- 建议：供应商品牌先限定字符串；连接字段统一在安全类型检查后做值校验，增加真实 PATCH 回归，保证返回 400/422 且事务不写入。

### t053_code_f002 - 环境变量凭据刷新成功后被写回异常打断

- 严重度：important
- 锚点：可观测行为回归；AC-012 要求已有 OAuth 凭据继续用于刷新和同步。
- 位置：`src/mail_core/accounts/credentials.py:315`、`src/mail_core/providers/oauth.py:107`。
- 问题：原 `_persist` 对 operator-managed `env:` 只读凭据无法写回时记录警告，仍允许使用新 Access Token。改成 `credential_edit` 后，上下文退出调用 `save_json_secret` 并直接抛 `ReadOnlyCredentialRef`。独立构造 EnvCredentialStore 与返回有效 Access Token 的 token endpoint 已复现：成功刷新后 `get_access_token()` 仍抛异常，使用该合法凭据来源的 Gmail/Graph 同步全部失败。原支持的只读凭据来源被隐式移除。
- 建议：保留只读来源的读取/刷新语义（只读缓存留在内存并明确无法持久化轮换），或经批准显式改变该公开支持范围；不要吞掉数据库真正持久化失败。增加 env: 刷新成功回归。

### t053_code_f003 - 导入脚本仍默认创建 Microsoft IMAP 账户

- 严重度：important
- 锚点：AC-018，相关导入接入路径须拒绝 Microsoft IMAP，生产代码移除 Microsoft IMAP 预设。
- 位置：`scripts/migrate_from_legacy_db.py:318`、`scripts/migrate_from_legacy_db.py:357`。
- 问题：该生产导入路径未调用新拒绝规则，仍把缺失 IMAP host 默认成 `outlook.office365.com`，并直接构造 Account 保存。输入旧 IMAP Outlook 账号或缺 host 的普通 IMAP 账号，导入成功后才在 provider 构建失败。虽然 Worker guard 阻断网络，但没有满足“导入接入路径拒绝”和“删除 Microsoft IMAP 预设”；会落下不可运行的账号配置。
- 建议：移除该 Microsoft 默认主机，在保存账户/凭据前复用明确的 Microsoft IMAP 拒绝校验；保留历史数据迁移边界，不增加 IMAP→Graph 身份转换。

### t053_code_f004 - Google OAuth 帮助缺少所需邮件权限说明

- 严重度：important
- 锚点：AC-006，Google API 帮助须说明匹配客户端和已授权 `gmail.modify` 范围。
- 位置：`src/frontend/src/lib/account_providers.ts:5`、`src/frontend/src/components/credential_help.tsx:15`。
- 问题：Google 帮助仅说明启用 API、同意屏幕、测试用户、客户端类型及令牌期限，未说明需要添加 `gmail.modify`。当前手动凭据主路径依赖用户在外部完成授权；按弹窗步骤操作仍无法确定需要授予哪些邮件权限，可能得到只能读取或无 Gmail 权限的 Token。`scope` 输入框没有默认提示，不能代替获取步骤。
- 建议：在 Google OAuth 对应帮助中明确所需 `gmail.modify` 权限及“填写 scope 不能扩大旧授权”；避免要求额外 gmail.send/全量 mail.google.com。帮助内容按当前 IMAP/OAuth 方式聚焦。

### t053_code_f005 - 自动供应商建议清除已手填的 IMAP 登录名

- 严重度：important
- 锚点：AC-002，切换邮箱或自动建议不得覆盖手动连接配置。
- 位置：`src/frontend/src/components/settings_account_form.tsx:39`、`src/frontend/src/components/settings_account_form.tsx:107`、`src/frontend/src/components/settings_account_form.tsx:116`。
- 问题：在新建表单先填独立登录名，再输入 `[REDACTED_EMAIL]`，域名建议调用 `changeVendor(..., false)`，无条件 `setUsername('')`。用户名输入没有设置保留标记；即使 host/port 已被手动填写，登录名仍被清空，提交时回退为邮箱地址，导致本应使用独立用户名的账号认证失败。
- 建议：跟踪独立登录名是否手动修改，自动供应商建议保留该值；跨不同协议切换只清除不适用的凭据，不清除仍适用的手动连接参数。

## 结论

- 本轮新发现：5 条 important，当前不满足合入条件。
- 已扫视角：安全、正确性、公开契约与 Breaking、性能与资源、架构可维护性、健壮性与可观测、文档及规格一致性。未发现 SQL 拼接或前端秘密持久化新路径；行锁串行化 DB 凭据编辑与刷新方向合理，但只读来源兼容遗漏。
- 未进表提示：`src/mail_core/accounts/service.py` 444 行并继续净增，按规则仅作拆分提示。生成 OpenAPI/TypeScript schema 排除文件行数评价；供应商表驱动不因行长/紧凑格式单独出 finding。新配置校验和表单提交分支较多，可在修复时保持职责清晰。
- 系统性 follow-up：无，以上均在 t053 承诺范围内。
- 审阅期间观察到 `tests/e2e/full_stack.spec.ts` 又出现变动，当前范围指纹已为 `71856d9e9d5ff202`；本报告保留派审注入指纹，修复后需按最终内容完整重审，不可直接复用 PASS。

### AC 复验方式

|AC|类别|证据|
|---|---|---|
|AC-001|re_verified|核对供应商 select、协议条件渲染及命名凭据字段。|
|AC-002|re_verified|精确域名表无子串匹配；独立登录名被自动清空，见 f005。|
|AC-003|re_verified|核对 QQ/网易/iCloud/Yahoo 主机、端口与密码标签；DTO 返回登录名。|
|AC-004|re_verified|Microsoft 只列 Graph，公共/机密字段及租户端点生成已核对。|
|AC-005|re_verified|Google 显示两种协议与应用密码前置说明。|
|AC-006|re_verified|Microsoft 权限说明存在，Google 所需范围遗漏，见 f004。|
|AC-007|re_verified|Zoho 提示计划、企业主机、数据中心与 2FA/SAML。|
|AC-008|re_verified|自定义 IMAP 字段及 Proton 限制提示，未放宽 private host/TLS。|
|AC-009|re_verified|已存 provider 初始化、禁切协议及空凭据编辑逻辑已核对。|
|AC-010|re_verified|DTO 显式白名单与前端秘密初始空值，不回显凭据 JSON。|
|AC-011|re_verified|按非空字段合并，在同一账户事务内写加密行，异常由应用服务回滚。|
|AC-012|re_verified|DB 行锁与缓存失效存在；env: 刷新回归，见 f002。|
|AC-013|re_verified|供应商/协议切换清空密码和 OAuth 草稿，载荷按当前协议构造。|
|AC-014|re_verified|非法端口和协议字段有校验；不合法品牌类型产生 500，见 f001。|
|AC-015|trust_prior|布局与焦点实测依赖 `.scratch/t053_e2e.log` 中 3 项通过；独立核对 CSS 宽度和 dialog 代码，不宣称另做真人交互。|
|AC-016|re_verified|帮助图标、嵌套原生 dialog、Esc 阻止冒泡及焦点恢复实现已核对。|
|AC-017|re_verified|核对两家注册步骤与 Token 类型区分，无第三方获取网站。|
|AC-018|re_verified|账户/API/factory guard 存在，但导入脚本遗漏且保留旧预设，见 f003。|

coverage = 17 / 18

verdict: FAIL

## Round 2 (2026-10-24T14:14:22+08:00)

reviewed_scope: 7eae57520071c604

### 前轮 finding 复核

- `t053_code_f001`：已消除。`connection.py:35` 对 profile 先判断字符串；独立调用原输入现在返回 ValueError。对其余新增字段作进一步检查时发现独立登录名校验遗漏，单列 f006。
- `t053_code_f002`：修不彻底。只读凭据首次刷新不再抛写回异常，但进程内新 Access Token 和轮换 Refresh Token 未被后续调用使用，见下文。
- `t053_code_f003`：已消除。`legacy_account_connection` 删除 Microsoft host 默认值，且 `migrate` 在迁移组之前对所有源账户预检；Microsoft IMAP 和缺主机配置在写入前拒绝。
- `t053_code_f004`：已消除。Google 帮助补充 gmail.modify 及“不额外申请发送/全量范围”，已有 scope 输入说明不会扩大旧授权。
- `t053_code_f005`：已消除。`changeVendor` 不再清空 username，自动供应商建议保留手填登录名。

### t053_code_f002 - 只读凭据刷新后仍重复使用旧 Refresh Token

- 严重度：important（前轮 finding 继续存在）
- 锚点：AC-012；有效 Token 缓存及轮换凭据必须继续可用，不能回退旧快照。
- 位置：`src/mail_core/providers/oauth.py:107`、`src/mail_core/providers/oauth.py:109`、`src/mail_core/accounts/credentials.py:311`。
- 问题：每次 get_access_token 仍从 env: 读原始旧凭据，`self._cached=dict(data)` 也在网络刷新之前。allow_readonly 只消除退出异常，没有保留新 Token。独立复验同一 EnvCredentialStore 客户端连续调用两次：两次均返回成功，但发出 2 次刷新请求，表单 Refresh Token 均为 old，即便第一次响应已返回 rotated 且 Access Token 仍有效。供应商令牌轮换后旧 RT 失效时，下次请求将认证失败；即使不失效，也每次 API 请求都额外刷新。
- 建议：只读来源保留进程内新凭据与有效 Access Token 缓存，之后刷新用轮换后的 RT；数据库来源仍应每次锁行重载以观察跨进程修改。测试需覆盖同一客户端连续读取、强制刷新与轮换后的 RT，而非只验证首次成功。

### t053_code_f006 - 非字符串独立登录名在提交后使账户响应及列表失败

- 严重度：important
- 锚点：AC-011、AC-014；无效连接字段应在写入前拒绝且不留下半份配置。
- 位置：`src/mail_core/accounts/connection.py:40`、`src/mail_core/mail/application/accounts.py:105`、`src/mail_core/api/accounts.py:36`。
- 问题：新增公开 imap_user 字段是 str，但请求 config 仍是任意 JSON，validator 未检查 imap_user/username 类型。独立调用生产 validator，`config={'imap_host':'imap.example.test','imap_user':['invalid']}` 被接受；同配置构造 AccountOut 则触发 ValidationError。应用服务在构造响应之前已 session.commit，因此 POST/PATCH 返回错误却把无效用户名和其余变更写入 DB，随后 GET /api/accounts 遍历该账户时仍会失败，阻断设置列表。
- 建议：写入前检查独立登录名两种键仅接受合法字符串或明确规定的清空值；真实 API/PG 回归同时断言失败事务未改账户及账户列表仍可读取。

### 全量复核及 AC 复验方式

- 本轮重新检查全部 diff，包含新增导入预检、只读凭据上下文分支、账户 API/DTO、表单与帮助、OpenAPI 生成面及最终 specs/blueprint。安全、正确性、契约与 Breaking、性能与资源、架构可维护性、健壮性与可观测、文档与规格七个视角均已扫描。
- 独立运行：`scripts/run-mail-core-tests.sh unit -k 'provider_account_forms or account_credentials_unit or oauth_transport or oauth_allowlist' --no-cov`：26 passed、497 deselected；该命令未运行 PostgreSQL 套件，不据此声明 DB 集成验证通过。
- 独立脚本复验：原 profile=[] 输入已 ValueError；env: 连续刷新请求复现 f002；imap_user 数组通过连接校验但响应模型拒绝，复现 f006。
- AC-001～AC-014、AC-016～AC-018：`re_verified`，重新查证实际实现及相关断言，其中 AC-011/012/014 仍有上述缺陷。AC-015：`trust_prior`，依赖已有窄屏/焦点 E2E 证据；本轮未重跑浏览器。
- 覆盖率：coverage = 17 / 18。
- 本轮新发现：1 条 important（f006）；前轮 remaining：1 条 important（f002）。
- 未进表提示：`accounts/service.py` 行数与复杂度提示同前轮，生成 schema 与供应商表驱动排除规模评价。无新范围外问题。
- 系统性 follow-up：无；两项均须在本 task 修复后完整重审。

verdict: FAIL

## Round 3 (2026-10-24T14:32:34+08:00)

reviewed_scope: 4072f20530f238a5

### 前轮 finding 复核

- `t053_code_f002`：已消除。`src/mail_core/accounts/credentials.py:280,314-315` 新增 `readonly_cache` 参数，对 `EnvCredentialStore`（含 `CompositeCredentialStore` 路由的 `env:` 引用）在非空缓存时复用进程内最新凭据；`src/mail_core/providers/oauth.py:107-114,149` 在刷新成功后更新 `self._cached = dict(data)` 并传入 `readonly_cache=self._cached`。独立运行 `test_operator_managed_environment_refresh_caches_access_and_rotated_refresh_token` 验证：连续第二次 `get_access_token()` 命中缓存不重复发起 HTTP 刷新，强制刷新 `get_access_token(force_refresh=True)` 使用首次轮换返回的 `rotated-1`，且 `DbCredentialStore` 仍每次经数据库行锁重载，跨进程轮换与编辑互不覆盖。
- `t053_code_f006`：已消除。`src/mail_core/accounts/connection.py:42-44` 在连接校验入口对 `imap_user` 与 `username` 强制检查非 `None` 时必须为 `str`；`src/mail_core/accounts/service.py:152-154` 在 `update_account` 中当 `config_patch` 传入空字符串或空白 `imap_user`/`username` 时从 `config` 移除对应键；`src/mail_core/mail/application/accounts.py:106-113` 与 `src/mail_core/api/accounts.py:60-64` 仅在非空字符串时输出 `imap_user`。独立运行 PG 集成测试 `test_invalid_imap_user_rejected_before_commit_and_accounts_list_remains_readable` 验证：非法数组在提交前返回 400、事务完整回滚、`GET /api/accounts` 正常返回，空字符串成功清除独立登录名。
- Round 1 已消除项（`t053_code_f001`、`t053_code_f003`、`t053_code_f004`、`t053_code_f005`）：复核确认未发生回退。

### 全量复核及 AC 复验方式

- 对照 `git -C '[REDACTED_LOCAL_PATH]' diff e124a27a4baa5917fd39f3bb5190d54334014639` 全量复核 27 个变更文件，覆盖安全、实现正确性、公开契约与 Breaking、性能与资源、架构可维护性、健壮性与可观测、文档与规格一致性七个视角。
- 独立执行后端单测：`scripts/run-mail-core-tests.sh unit -k 'provider_account_forms or account_credentials_unit or accounts_api_unit or oauth_transport or oauth_allowlist' --no-cov`（35 passed）。
- 独立执行后端 PG 集成测试：`scripts/run-mail-core-tests.sh run -k 'provider_accounts_pg or provider_account_forms' --no-cov`（19 passed）。
- 独立执行前端单测与契约检查：`npm --prefix src/frontend test -- --run src/components/provider_account_form.test.tsx src/components/SettingsModal.test.tsx src/components/settings_redesign.test.tsx`（41 test files / 289 tests passed，`openapi:check` 与 CSS token 检查通过）。

|AC|类别|证据|
|---|---|---|
|AC-001|re_verified|核对 `account_providers.ts`、`settings_account_form.tsx` 与前端单测，覆盖全部直接支持供应商与自定义 IMAP、命名凭据字段、添加/编辑复用。|
|AC-002|re_verified|核对 `inferVendor` 精确域名匹配、子域名隔离与 `manualVendor`/`connectionEdited` 保护，手填服务器和独立登录名不被自动建议覆盖。|
|AC-003|re_verified|核对 QQ/Foxmail、网易、iCloud、Yahoo 预设、独立登录名读写与清空逻辑，编辑旧账户保留已存参数。|
|AC-004|re_verified|核对 Microsoft 仅提供 Graph OAuth、公共/机密客户端字段校验、租户端点生成及帮助说明。|
|AC-005|re_verified|核对 Gmail API 与 IMAP 应用专用密码双路径、字段必填规则与前置提示。|
|AC-006|re_verified|核对 Microsoft `Mail.ReadWrite`/`offline_access` 与 Google `gmail.modify` 权限说明，不额外要求发送或全量范围。|
|AC-007|re_verified|核对 Zoho 个人/企业主机提示、数据中心说明、免费计划限制及 2FA/SAML 应用密码提示。|
|AC-008|re_verified|核对自定义 IMAP 字段、Proton Bridge 限制提示及 `validate_imap_host` SSRF/TLS 边界保持不变。|
|AC-009|re_verified|核对编辑态锁定已有协议、历史账户缺省品牌推断及仅改分组不强制重填凭据。|
|AC-010|re_verified|核对 `AccountDTO`/`AccountOut` 白名单字段与 PG 测试，秘密永不回显，空输入保持原凭据不变。|
|AC-011|re_verified|核对 `merge_credentials`、`validate_connection` 与 PG 事务回滚测试，局部更新保留其余字段，校验失败无半份写入。|
|AC-012|re_verified|核对 OAuth 凭据/客户端类型变更清除缓存、DB 行锁串行化刷新与编辑、`env:` 只读凭据进程内缓存及轮换 RT 保留。|
|AC-013|re_verified|核对供应商/协议切换清空草稿、按当前协议过滤提交载荷及关闭重开不残留秘密。|
|AC-014|re_verified|核对前后端字段与类型校验（含 `provider_profile`、`imap_user`/`username`、端口、HTTPS token_uri 白名单），错误响应不泄露提交秘密。|
|AC-015|trust_prior|依赖 `.scratch/t053_e2e.log` 浏览器窄屏/焦点 E2E 通过记录，并结合 `settings_account_form.tsx`、`credential_help.tsx` 与 `provider_account_forms.spec.ts` 代码核对。|
|AC-016|re_verified|核对帮助按钮无障碍名称、`CredentialHelp` 原生模态弹窗、Esc 仅关顶层弹窗并恢复触发点焦点。|
|AC-017|re_verified|核对 Google IMAP/OAuth 与 Microsoft OAuth 分步说明及各类 ID/Secret/Token 区分。|
|AC-018|re_verified|核对 `reject_microsoft_imap` 在创建、编辑、导入脚本预检及 `build_provider` 全路径拦截，旧软提示与默认主机已移除。|

coverage = 17 / 18

### 结论

- 本轮新发现：0 条
- 未进表的提示：`src/mail_core/accounts/service.py`（447 行）超过 400 行阈值，按规则仅在结论段作拆分提示；OpenAPI/TypeScript 生成文件与供应商配置表排除规模评价。
- 总体判断：前轮遗留的 `t053_code_f002` 与 `t053_code_f006` 均已彻底修复并经单测与 PG 集成测试独立验证，18 条 AC 全部满足且无未解决的 critical / important 问题。
- 系统性 follow-up：无

verdict: PASS
