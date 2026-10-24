# Task review t053（reviewer_focus: 测试）

- task：`t053_provider_account_forms`
- spec：`docs/tasks/t053_provider_account_forms/spec.md`
- diff_anchor：`e124a27a4baa5917fd39f3bb5190d54334014639`
- target：`git -C '/Users/karson/kar/code/kkmail' diff e124a27a4baa5917fd39f3bb5190d54334014639`
- round：1
- reviewed_at：2026-10-24T14:09:04+08:00

reviewed_scope: c862c6944024541a

## Findings

### t053_test_f001 - 权限与持续访问帮助完全缺少行为测试

- 严重度：important
- 锚点：AC-006，要求 Google/Microsoft 帮助说明实际所需授权范围，且不额外要求发信或全量范围。
- 位置：`src/frontend/src/components/provider_account_form.test.tsx:12`、`tests/e2e/provider_account_forms.spec.ts:4`。
- 问题：现有组件与浏览器测试仅打开 Google IMAP 帮助并断言“两步验证”；未打开 Microsoft OAuth 或 Google API 帮助并验证 `Mail.ReadWrite`、持续访问、`gmail.modify` 及不额外申请发信范围。全仓测试搜索未发现针对本帮助行为的相应断言。账号图标测试与 token grant 测试不验证用户看到的配置要求；AC-006 完全没有行为证据。
- 建议：从实际新增/编辑表单点击帮助图标，按当前供应商/方式验证授权要求和禁止误导的范围；不要只对导出的常量做自证断言。

### t053_test_f002 - Zoho 供应商要求完全没有测试覆盖

- 严重度：important
- 锚点：AC-007，要求 Zoho 的 IMAP 前置开关、计划限制、个人/付费企业主机、数据中心和 2FA/SAML 应用密码说明。
- 位置：`src/frontend/src/components/provider_account_form.test.tsx:12`、`src/frontend/src/lib/account_providers.ts:13`。
- 问题：本 task 所有新增组件/E2E 测试均未选择 Zoho，既没有验证独立字段/服务器可修改，也没有验证对应帮助内容或地区账号不得被强制覆盖。全仓未发现其他 Zoho 表单测试；AC-007 完全无测试。现有 Google 主机断言不能代表不同供应商规则。
- 建议：新增组件交互测试，选择 Zoho、打开帮助、检查个人/企业与数据中心限制和应用密码要求，并修改服务器验证仍可保留用户值。

### t053_test_f003 - 凭据草稿跨供应商及关闭重开隔离没有测试

- 严重度：important
- 锚点：AC-013，切换供应商/认证方式、关闭表单后不得残留或提交前一种方式的秘密。
- 位置：`src/frontend/src/components/provider_account_form.test.tsx:14`、`src/frontend/src/components/provider_account_form.test.tsx:34`、`tests/e2e/provider_account_forms.spec.ts:20`。
- 问题：目前切换供应商的测试在切换前未填写任何凭据；唯一提交载荷测试只编辑同一 Graph 账户的 Refresh Token。没有测试先填密码/Token，再切换供应商或 Google API/IMAP，检查新字段与实际提交载荷；也没有关闭重开后检查秘密为空。故即使移除清理草稿逻辑，现有测试仍可能全部通过，AC-013 完全缺少可证伪测试。
- 建议：通过生产表单交互先填入可识别的密码/Token，切换供应商/认证方式，再提交并断言载荷仅含当前有效字段；关闭重开验证秘密为空，同时检查浏览器持久存储未保存它们。

## 结论

- 改测方向复核：既有 expect 未被改为新实现输出；`SettingsModal.test.tsx:412` 新增必填密码输入属于有效夹具补齐，断言保留。`test_accounts_api_unit.py:150` 同理补齐新建连接必填数据。`test_account_credentials_unit.py:44` 新增主机校验 mock 不承担安全校验证据，仅保留原来的 store/session 参数测试；真实 API/PG 测试另行覆盖保存和回滚。
- 删除测试复核：删除 `settings_redesign.test.tsx` 的 JSON 对象编辑器测试合理，spec 明确移除该输入路径；新的命名字段提交与真实 API/PG 校验覆盖新语义。`full_stack.spec.ts:113` 将旧 JSON 输入改为密码框 `.fill()` 是真实 UI 输入适配，后续 Worker/邮件断言未删除、未放宽，不构成迁就实现。
- 独立执行：`npm --prefix /Users/karson/kar/code/kkmail/src/frontend exec -- vitest run src/components/provider_account_form.test.tsx`，3 passed。真实 PG 和全量前端测试日志分别为 35 passed、278 passed；前者本 reviewer 未重跑 DB，依赖所列隔离运行日志。
- 黑盒证据：原 `.scratch/t053_full_stack.log` 为 1 failed / 7 passed，错误来自已移除 JSON 编辑器。实现侧已修正输入步骤并重跑；本轮不把尚未独立核对的后续日志计为初次黑盒成功。已有 `.scratch/t053_e2e.log` 的 3 项浏览器测试通过，但没有覆盖上述缺口。
- 危险模式：未发现新增 only、条件跳过断言、容差/重试放宽或程序赋值冒充点击/键盘。新增 PG skipif 为项目约定，真实 PG 日志证明相应用例已执行，不是豁免 DB 门禁。现有全栈用例中原有条件点击未被本 task 弱化。
- 正交体检：已扫测试相关安全（草稿/秘密）、正确性（保存/回滚）、契约（供应商矩阵）、性能/资源（轮换并发）、架构（边界桩）、健壮性（异常校验）、测试/文档/规格。阻断项为上列三个完整 AC 测试空白，无凑数 finding。
- 本轮新发现：3 条 important。
- 未进表的提示：QQ/网易/iCloud/Yahoo 预设、独立 IMAP 登录名保存再编辑、前端精确域名自动建议、Proton 限制等可补参数化场景；已有相关 AC 的部分路径被更高层测试触达，未将“可测更细”当作额外 blocker。
- 总体判断：实现已有有效的真实 API/PG 与 UI 行为测试，但三条新 AC 仍完全无可证伪行为测试，当前 FAIL。
- 系统性 follow-up：无，本 task 内补齐。

### AC 复验方式

以下披露审阅方式，不表示每条 AC 已通过。

|AC|类别|证据或缺口|
|---|---|---|
|AC-001|re_verified|组件新增/编辑均渲染 AccountDialog；新测试通过真实 DOM 选择 Google/Microsoft，确认 JSON 输入移除。|
|AC-002|re_verified|读取 `does not replace manually entered host when the address changes` 断言，独立组件测试已通过；精确域名正反例可扩展。|
|AC-003|re_verified|Google 主机 E2E、既有 `SettingsModal` 编辑配置载荷和 host/port 断言保留；其他预设/独立登录名可扩展。|
|AC-004|re_verified|Microsoft UI 只显示 OAuth 字段；生产 validator 的机密客户端缺 Secret 测试确实抛错，公共 Graph API 创建用例有成功断言。|
|AC-005|re_verified|实际表单 Google API/IMAP 选择与 Google 主机、两步验证帮助有断言；参数校验调用生产逻辑。|
|AC-006|re_verified|全仓检索与逐测试阅读确认权限帮助无行为测试，见 f001。|
|AC-007|re_verified|全仓检索确认 Zoho 表单未被任何测试选择或核对，见 f002。|
|AC-008|re_verified|全栈真实 IMAP 使用自定义主机/端口；新增 API 密码校验测试触达生产逻辑，Proton 提示可扩展。|
|AC-009|re_verified|既有编辑测试保留旧 host、port、group 并提交部分配置；Graph 命名字段编辑测试不切协议。|
|AC-010|re_verified|真实 PG 用例检查响应不含秘密，现有 DTO 白名单测试仍保留；组件编辑秘密初始为空。|
|AC-011|trust_prior|已逐项读取真实 PG 合并、字段失败回滚及配置失败不保存断言；运行成功依赖 `.scratch/t053_backend_final.log`。|
|AC-012|trust_prior|真实 PG 并发两客户端刷新仅调用一次 token 端点、编辑后旧客户端使用新 Refresh Token；执行结果依赖同一 PG 日志。|
|AC-013|re_verified|确认没有填写秘密后切换/关闭重开的测试，见 f003。|
|AC-014|re_verified|API 与生产 validation/factory 拒绝错误组合、密码缺失、非法端口及 Microsoft IMAP；既有 allowlist 测试仍在。|
|AC-015|re_verified|读取 Playwright 实际填长 Token、320px 检查与取消交互，另有旧 settings 真实原生 dialog 焦点断言。|
|AC-016|re_verified|新增 E2E 用 Escape 关闭最上层帮助、恢复图标焦点且保留账户 dialog，组件测试也实际点击开关帮助。|
|AC-017|re_verified|Google IMAP 两步验证帮助由实际弹窗断言触达，OAuth 分步帮助的其他细节可扩展；f001 单独覆盖完全空白的权限帮助 AC。|
|AC-018|re_verified|参数化直接调用生产 factory/validator，API/PG 检查拒绝 Microsoft IMAP 且不回显密码；未恢复 XOAUTH2。|

coverage = 16 / 18

verdict: FAIL

## Round 2 (2026-10-24T14:13:54+08:00)

reviewed_scope: 7eae57520071c604

### 前轮 findings 复核

- `t053_test_f001`：已消除。`provider_account_form.test.tsx:75` 参数化打开真实 Google/Microsoft 表单帮助，逐项断言 `gmail.modify`、不额外申请范围、`Mail.ReadWrite`、`offline_access` 和后台同步说明；实际帮助内容同步补齐，未以测试常量自证代替交互。
- `t053_test_f002`：已消除。`provider_account_form.test.tsx:53` 参数化选择七个 IMAP 供应商，验证主机、993/TLS、凭据标签和帮助链接；Zoho 分支必定由 `it.each` 的明确 Zoho 数据行执行，并在 `:72` 断言个人、付费企业、数据中心、免费计划、两步验证与 SAML。该条件是参数化场景分发，前置满足已有数据保证，未静默跳过待测行为。
- `t053_test_f003`：已消除。`provider_account_form.test.tsx:86` 先输入 Google 客户端和令牌、切 IMAP 输入密码、再切 Microsoft，检查秘密输入为空并检查实际 Graph 提交载荷无 Google 秘密、密码或 IMAP 主机。`:111` 通过 Harness 实际关闭重开，检查密码清空；在填写后和重开后扫描 localStorage/sessionStorage 所有值。先前无效的“以秘密作为 key 查询”断言已移除，而非仅补同样无效断言。

### 本轮新增扫描与验证

- 独立核对实际 diff 指纹：`7eae57520071c604`，与本轮注入 prompt 一致。所有实现/测试新文件均进入 diff，review 报告本身为排除项。
- 独立执行生产组件测试：`npm --prefix /Users/karson/kar/code/kkmail/src/frontend exec -- vitest run src/components/provider_account_form.test.tsx`，14 passed。
- 独立执行新增后端合同回归：`KKMAIL_TEST_MODE=unit .venv/bin/python -m pytest tests/mail_core/test_provider_account_forms.py -q --no-cov`，14 passed。该命令明确为无 DB 快速验证，未冒充 PostgreSQL 运行。
- 核对 `.scratch/t053_backend_review_final.log`：真实隔离 PostgreSQL 37 passed，并有迁移与清理成功记录；核对 `.scratch/t053_full_stack_final.log`：真实认证、IMAP 新增和 Worker 同步等 8 passed，数据库已清理。未将旧失败日志覆盖为成功，也未把边界桩伪称真实服务商授权。
- 新增 `test_invalid_profile_type_is_a_validation_error` 以非法列表输入调用生产校验函数；`test_operator_managed_environment_refresh_still_returns_access` 调用真实 EnvCredentialStore/OAuthTokenClient，只替换远端 token HTTP 边界，并验证环境内凭据未被修改。
- `test_legacy_import_does_not_create_microsoft_imap_defaults` 调用真实 import helper，覆盖 Microsoft 域名、Microsoft 主机和空主机三类拒绝；未 mock 掉拒绝逻辑。原有正式导入路径使用同一 helper，在实际写入前校验。
- 改测方向复核：无迁就实现修改预期。既有 JSON 编辑器测试整块删除有明确新规格依据，真实全栈输入步骤仅改为现有密码框，后续验证原样保留。追加参数化测试使用真实组件交互，边界 fetch 桩仅记录真实请求载荷；未 mock 被测表单逻辑。
- 危险模式扫描：未新增 skip/only、恒真断言、删除关键断言、放宽阈值或异常吞噬。`toMatchObject` 属新增请求形状断言，紧接完整 JSON 秘密负向断言，未把旧精确断言弱化。已存在 DB skipif 仍由项目隔离运行器保证实际执行。
- 七视角复核：安全（秘密隔离/客户端类型）、正确性（保存/回滚）、契约（供应商参数化/导入拒绝）、性能与资源（轮换锁）、架构（外部边界桩）、健壮性（非法 profile、只读环境凭据）、测试与文档/规格均已复核；无新增具体测试缺陷。
- 本轮新发现：0 条。
- 未进表的提示：可继续扩展每种编辑状态的参数组合，但已有 AC 的可观察主路径均有直接测试；未将额外 case 建议当 blocker。
- 系统性 follow-up：无。
- 总体判断：前轮三个测试阻断已消除，现无未解决 critical/important；PASS。

### AC 复验方式

|AC|类别|本轮证据|
|---|---|---|
|AC-001|re_verified|实际组件 Google/Microsoft 接入切换、命名字段与编辑请求；参数化全部支持项。|
|AC-002|re_verified|保留手填服务器及独立登录名测试独立通过，完整域名规则经源码核对。|
|AC-003|re_verified|七供应商参数化主机/993/TLS/凭据标签，加既有 IMAP 编辑配置测试。|
|AC-004|re_verified|Microsoft OAuth 字段、机密客户端校验和真实帮助文案断言。|
|AC-005|re_verified|Google API/IMAP 切换、主机、两步验证说明及其命名凭据测试。|
|AC-006|re_verified|Google/Microsoft OAuth 帮助参数化真实交互，f001 已消除。|
|AC-007|re_verified|Zoho 数据行必执行，对数据中心、计划、企业/个人与2FA/SAML作断言，f002 已消除。|
|AC-008|re_verified|自定义 IMAP 主机输入与真实全栈用例；Proton 限制分支经代码核对，无扩大私网绕过。|
|AC-009|re_verified|既有 IMAP 编辑保留配置和 Graph 仅部分凭据请求；无静默协议转换。|
|AC-010|re_verified|响应白名单/秘密负向断言、空编辑字段与实存凭据合并测试。|
|AC-011|trust_prior|读取真实 PG 合并与失败回滚断言，执行证据依赖 `.scratch/t053_backend_review_final.log` 37 passed。|
|AC-012|trust_prior|两独立客户端并发刷新及编辑后使用新 Refresh Token；运行结果依赖同一真实 PG 日志。|
|AC-013|re_verified|秘密输入后跨方式/供应商载荷隔离、关闭重开及所有持久存储值检查，f003 已消除。|
|AC-014|re_verified|生产 validator/factory 与非法 profile、端口、凭据、Microsoft 接入拒绝回归独立通过。|
|AC-015|re_verified|浏览器长 Token 及窄屏断言、原生 dialog 取消/焦点恢复，源码与日志一致。|
|AC-016|re_verified|参数化点击帮助及既有浏览器 Escape/焦点恢复断言。|
|AC-017|re_verified|多供应商帮助实际渲染与 OAuth 凭据术语、注册及权限文案测试。|
|AC-018|re_verified|生产 factory/API/legacy import 对 Microsoft IMAP 拒绝，空主机不得回填 Microsoft 默认值。|

coverage = 16 / 18

verdict: PASS

## Round 3 (2026-10-24T14:30:01+08:00)

reviewed_scope: 4072f20530f238a5

### 前轮 findings 复核

- `t053_test_f001`：已消除（保持）。`src/frontend/src/components/provider_account_form.test.tsx:75` 参数化打开 Google 与 Microsoft 真实帮助弹窗并断言 `gmail.modify`、`Mail.ReadWrite`、`offline_access` 及不额外申请发信/全量范围。
- `t053_test_f002`：已消除（保持）。`src/frontend/src/components/provider_account_form.test.tsx:53` 参数化覆盖七类 IMAP 供应商并在 Zoho 数据行（`:72`）断言个人/付费企业主机、数据中心、免费计划、两步验证与 SAML。
- `t053_test_f003`：已消除（保持）。`src/frontend/src/components/provider_account_form.test.tsx:86` 与 `:111` 覆盖跨供应商/认证方式切换清空秘密草稿、提交载荷隔离、关闭重开清空及 `localStorage`/`sessionStorage` 无残留。

### 本轮新增测试复核与验证

- 仓库落点校验：`git rev-parse --show-toplevel` 精确等于 `/Users/karson/kar/code/kkmail`。
- 独立执行后端单测：`KKMAIL_TEST_MODE=unit .venv/bin/python -m pytest tests/mail_core/test_provider_account_forms.py -q --no-cov`，14 passed。
- 独立执行前端组件测试：`npm --prefix /Users/karson/kar/code/kkmail/src/frontend exec -- vitest run --root /Users/karson/kar/code/kkmail/src/frontend src/components/provider_account_form.test.tsx`，14 passed。
- 核对 `tests/mail_core/test_provider_account_forms.py`：
    - `test_invalid_profile_and_imap_user_types_are_validation_errors`（`:55`）直接调用生产 `validate_connection`，验证非法 `provider_profile: []` 及 `require_credentials=False` 下非法 `imap_user`/`username` 列表类型均抛出字段级 `ValueError`。
    - `test_operator_managed_environment_refresh_caches_access_and_rotated_refresh_token`（`:70`）通过真实 `EnvCredentialStore` 与 `OAuthTokenClient`（仅在 HTTP token 端点边界注入 `token_post`）验证：首次刷新获取 `renewed-1`，二次调用命中内存缓存不重复请求（`len(calls) == 1`），`force_refresh=True` 时携带内存缓存中轮换后的 `rotated-1` 发起第二次刷新（`calls[1]['refresh_token'] == 'rotated-1'`），且底层只读环境变量保持原值不变。
- 核对 `tests/mail_core/test_provider_accounts_pg.py`：
    - `test_invalid_imap_user_rejected_before_commit_and_accounts_list_remains_readable`（`:83`）在真实 API/PG 路径验证：创建时传入非法 `imap_user: ['invalid']` 返回 400 且不回显密码；合法创建 `imap_user: 'custom-login'` 返回 200 且 `imap_config.imap_user` 正确返回；PATCH 同时修改 `display_name` 与非法 `imap_user: ['invalid']` 返回 400 且事务完整回滚（`display_name` 仍为 `None`、`imap_user` 仍为 `'custom-login'`）；PATCH 传入空串 `imap_user: ''` 成功清除该字段且响应 `imap_config` 不再含 `imap_user`；后续 `GET /api/accounts` 返回 200 且账户列表正常可读。
- 核对 `.scratch/t053_backend_r3.log`：真实隔离 PostgreSQL 完成全量迁移并执行测试套件，记录 `41 passed, 483 deselected` 且测试库正常清理。
- 改测方向与危险模式复核：本轮仅在 `test_provider_account_forms.py` 与 `test_provider_accounts_pg.py` 新增/强化正向与负向回归断言，无迁就实现改测，无恒真断言、弱化断言、`skip`/`only` 或内部逻辑 mock。
- 本轮新发现：0 条。
- 未进表的提示：无。
- 系统性 follow-up：无。
- 总体判断：前轮 findings 均已闭环，本轮新增的输入类型校验、只读环境凭据轮换缓存与 IMAP 登录名增删改回滚回归测试可信且覆盖充分；PASS。

### AC 复验方式

|AC|类别|本轮证据|
|---|---|---|
|AC-001|re_verified|组件测试与 E2E 覆盖全部直接支持供应商与自定义 IMAP、命名字段展示及编辑复用。|
|AC-002|re_verified|完整域名后缀负例、自定义域名手选及手填主机/登录名不被自动建议覆盖均已验证。|
|AC-003|re_verified|七供应商参数化预设校验，且 `test_invalid_imap_user_rejected_before_commit_and_accounts_list_remains_readable` 完整验证 `imap_user` 保存、读取与清空。|
|AC-004|re_verified|Microsoft 仅 Graph OAuth、公共/机密客户端 `client_secret` 规则、租户令牌端点与帮助说明均已验证。|
|AC-005|re_verified|Gmail API 与 IMAP 应用专用密码双路径、字段必填规则及两步验证提示均已验证。|
|AC-006|re_verified|Google/Microsoft OAuth 权限范围与不额外申请发信/全量权限说明经真实组件弹窗验证。|
|AC-007|re_verified|Zoho 预设、个人/付费企业主机、数据中心、计划限制及 2FA/SAML 应用密码提示经参数化测试验证。|
|AC-008|re_verified|自定义 IMAP 全栈与单测通过；Proton 域名限制提示与不放开私网/TLS 边界经源码与 diff 核验。|
|AC-009|re_verified|编辑保持已存协议与连接配置、不静默切换协议、历史账户只改分组无须重填凭据均已验证。|
|AC-010|re_verified|API 响应白名单与秘密不回显断言、编辑框初始为空且留空保持不变均已验证。|
|AC-011|trust_prior|已核查 `test_provider_accounts_pg.py` 中局部凭据合并、非法字段/非法 `imap_user` 400 事务回滚与脱敏断言；真实 PG 执行结果依赖 `.scratch/t053_backend_r3.log`（41 passed）。|
|AC-012|trust_prior|已核查 `test_operator_managed_environment_refresh_caches_access_and_rotated_refresh_token`（单测独立复跑通过）及 `test_two_token_clients_serialize_rotation_and_observe_credential_edit`；真实 PG 并发轮换执行结果依赖 `.scratch/t053_backend_r3.log`（41 passed）。|
|AC-013|re_verified|切换供应商/认证方式清空草稿、提交载荷隔离、关闭重开清空及持久存储无秘密残留均已独立验证。|
|AC-014|re_verified|`validate_connection` 与 API 拒绝缺失字段、非法端口、非法 `provider_profile`/`imap_user` 类型及不支持组合，保留 SSRF 与 HTTPS token_uri 白名单。|
|AC-015|re_verified|Playwright 窄屏 320px 布局无横向溢出、长 Token 输入、可访问标签与原生 dialog 焦点恢复均已验证。|
|AC-016|re_verified|添加/编辑帮助图标点击与键盘打开、按供应商切换内容、Esc 关闭最上层弹窗并恢复图标焦点均已验证。|
|AC-017|re_verified|Google IMAP、Google OAuth、Microsoft OAuth 分步帮助与术语区分（Client ID / secret value / secret ID / ID Token / Access Token）均已验证。|
|AC-018|re_verified|API、validator、provider factory 及 legacy import 均拒绝 Microsoft IMAP，生产代码已移除 Microsoft IMAP 支持分支与软提示。|

coverage = 16 / 18

verdict: PASS
