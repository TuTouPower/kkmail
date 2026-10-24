# Task review t055（reviewer_focus: 代码）

- task：`t055_microsoft_oauth_callback`
- spec：`docs/tasks/t055_microsoft_oauth_callback/spec.md`
- diff_anchor：`e1dee25`
- target：`git -C '/Users/karson/kar/code/kkmail' diff e1dee25`
- round：1
- reviewed_at：2026-10-24T19:11:15+08:00

reviewed_scope: 78d028fee03434f9

## Findings

### t055_code_f001 - 网页编辑旧 Graph 账户自动升级为机密客户端，普通保存因缺 Secret 失败

- 严重度：important
- 锚点：AC-001（既有 Graph 未经用户操作不强制重新授权）、AC-012（重新授权及编辑保持原账户配置），以及可观测回归：旧公共客户端账户仅修改分组或原样点击保存，返回 `credentials.client_secret: required`。
- 位置：`src/frontend/src/components/settings_account_form.tsx:36`、`src/frontend/src/components/settings_account_form.tsx:126-127`、`src/frontend/src/components/settings_account_form.tsx:251`；拒绝写入点 `src/mail_core/accounts/service.py:129-134`。
- 问题：既有 Graph 账户未记录 `oauth_client_type` 时，原有效类型按 public 处理；新增 metadata effect 对这种旧账户自动设置 Web 默认 confidential。提交代码将这一自动默认变化当成显式配置修改，发送 `config.oauth_client_type=confidential`。旧公共凭据只有 Client ID/Refresh Token，后端因此要求新增 Client Secret，造成用户没有发起 OAuth 或编辑应用类型也无法保存普通设置。旧 Gmail 元数据缺类型时也受同一修改影响。
- 独立复现：`.scratch/review_t055_form.test.tsx` 运行真实 AccountDialog、Web metadata，直接点击保存，捕获 PATCH 载荷含 confidential；断言不应隐式升级失败，日志 `.scratch/review_t055_form_repro.log`。随后 `.scratch/review_t055_backend_repro.py` 在真实隔离 PG 创建无类型字段、无 Secret 的合法 Graph 账户，执行组件同样 PATCH，返回 400 `{"detail":"credentials.client_secret: required"}`；日志 `.scratch/review_t055_backend_repro.log`。两个复现均未改实现或生产测试。
- 建议：区分“供新浏览器授权使用的默认类型”与“用户明确修改旧账户类型”。普通保存只提交显式变更；已有账户仅修改分组或原样保存时不写自动默认值，真正 OAuth 结果仍由服务端 flow 配置落库。补 Web legacy Graph/Gmail 普通保存回归，保持新建/主动授权的 Web 机密客户端要求。

## 结论

- 本轮新发现：1 条 important。
- 独立验证：真实 PG 定向 `37 passed / 2 skipped`（Google/Microsoft 显式 Electron 模式本轮未再次启动），前端账户组件 `21 passed`；额外旧账户组件与真实 API 复现均红，证据如上。实施侧最终显式 Electron 定向 `39 passed`、全后端 `560 passed`、全栈 `8 passed` 日志已核对，未将假供应商通过当作真实微软账号已连通。`git diff --check` 通过，重算 scope 一致。
- 七视角复核：
    - 安全：核查微软固定 authority/Graph 端点、租户输入、PKCE、会话/epoch、CSRF、加密与状态白名单；长 device_code 不返回前端，验证链接限制官方 HTTPS，错误不回显供应商原文。
    - 正确性：发现 f001；Graph 真实邮箱和远端用户 ID 核对、旧 Graph 无 ID 建立身份、重复邮箱/异用户拒绝及最终保存一致性已核查。
    - 公开契约/Breaking：检查 method/tenant/短码白名单 DTO 与 OpenAPI/TS 生成结果，现有账户不强制重新授权的意图被 f001 破坏。
    - 性能/资源：设备 poll POST 仅作为驱动；供应商轮询受服务端 next_poll_at、interval、跨进程引用锁及 429/slow_down 退避控制；GET 状态不触发轮询。核查 ProviderHttpError 已标准化 header 大小写、生产 transport 保留 Retry-After。
    - 架构/维护性：Google 协议提取后保留共享生命周期；最终保存延续 sidebar → Account/flow → credential/pointer 的顺序，未新增本轮已证明的反序。
    - 健壮性/可观测：核查取消后删除、过期/迟到成功拒绝、HTTP/注册/管理员策略错误指引；长码和 token 不进入日志或公开状态。
    - 文档/规格：核查 Entra 注册权限、Secret value、localhost 端口/路径差异、offline_access 自动申请、设备码步骤、Graph-only 边界及部署指南；无本轮额外文档缺口。
- legacy 租户复核：编辑初值 `account?.oauth_tenant || (account ? '' : 'common')` 使旧账户保持空输入；后端 `resolve_tenant` 优先复用原 config/已存 token_uri，未主动把 organizations 改为 common。该路径与 f001 的客户端类型回归不同。
- 未进表提示：`oauth_flow.py` 637 行、账户 application 417 行，仍超过 400 行维护建议；Google/Microsoft/device 协议已分别拆出。start/consume 与 stage 的高分支需要持续关注，复杂度本身不阻断。生成 OpenAPI/TS 文件不计。真实 Entra 注册/2FA/管理员同意明确属于有意不测，不出 finding。
- 系统性 follow-up：无。
- 总体判断：微软两条授权协议及安全/轮询核心行为具备实现和证据，但新增默认客户端类型破坏既有账户普通编辑，本轮 FAIL。

### AC 复验方式

- AC-001：`re_verified` — 核查新增/编辑入口及现有凭据复用；真实组件和 PG API 复现既有账户普通保存被隐式改型阻断（f001）。
- AC-002：`re_verified` — 核查命名 Client ID、Secret、tenant 字段，Web/桌面/设备类型及缺项提示；自动默认类型持久化问题见 f001。
- AC-003：`re_verified` — 核查微软 localhost 动态回调与固定 Web HTTPS Origin，查阅 Electron 生产 SPA/API/HTTP 集成代码与通过日志，保留无 Cookie 暂存/原会话保存边界。
- AC-004：`re_verified` — 独立运行微软请求构造测试；核查 authorization_code+PKCE 与 device_code 参数隔离、Graph 委托权限与租户 authority。
- AC-005：`re_verified` — 核查 /me id/mail 和 inbox 可访问性验证，Access Token 保持不透明；独立测试缺 mail/缺 mailbox 拒绝。
- AC-006：`re_verified` — 独立 PG 测试覆盖远端 ID/精确邮箱、旧账户无 ID/旧令牌撤销、客户端及租户不匹配/重复邮箱拒绝。
- AC-007：`re_verified` — 核查共享 owner/epoch/用途/消费检查及最后保存；独立运行跨供应商/重放/并发 poll 与一次性保存测试。
- AC-008：`re_verified` — 独立运行错误分类/旧凭据保留测试；核查 HTTP 超时、管理员/Secret/租户提示及凭据编辑行锁。
- AC-009：`re_verified` — 查阅新增和编辑帮助内容及独立组件断言：完整 Entra 注册步骤、租户/注册权限与管理员条件均有说明。
- AC-010：`re_verified` — 核查 Client ID/Refresh Token 角色解释、门户不可查看、设备短码操作语言与高级命名更新路径。
- AC-011：`re_verified` — 核查 Microsoft 仍仅 Graph；IMAP 拒绝入口未恢复，其他供应商 IMAP 逻辑未新增改动。
- AC-012：`re_verified` — 核查移动布局、秘密白名单、callback URL 清理与账户保存；普通编辑隐式类型升级回归见 f001。
- AC-013：`re_verified` — 独立组件验证设备码不需回调/Secret、短码显示/复制/官方链接/取消；核查剩余时间服务端期限来源。
- AC-014：`re_verified` — 独立后端验证 interval、pending、slow_down、429 Retry-After、跨进程锁、取消、epoch 与迟到成功拒绝。
- AC-015：`re_verified` — 独立测试官方验证 URI 拒绝恶意地址与长码不回显、设备结果仍经过身份与重复/编辑核对。
- AC-016：`re_verified` — 独立测试注册失败指引及帮助文案；设备码不自动换 Client ID/Secret，offline_access 自动请求。

coverage = 16 / 16 (100.0%)

verdict: FAIL

## Round 2 (2026-10-24T23:46:59+08:00)

reviewed_scope: 12e66374e938defc

### Findings

本轮零 finding。

### 前轮 finding 复核

- t055_code_f001：已消除。`settings_account_form.tsx:126-127` 仅对新建账户应用 metadata 默认类型，旧 Graph/Gmail 保持已存或隐式 public；`:251` 将普通保存的类型 PATCH 限定为显式编辑且值不同，真正授权结果继续由服务端 flow 配置写入。新增六项组件矩阵分别覆盖两家旧账户原样保存、移组、显式 confidential+Secret 升级，直接核对完整 PATCH 载荷；未用弱化服务端校验规避问题。
- 独立运行上述账户组件及既有供应商组件 → `27 passed`（`.scratch/review_t055_r2_frontend.log`）；独立真实 PG 两家旧账户普通保存/移组回归 → `2 passed`（`.scratch/review_t055_r2_backend.log`），同时确认显式 confidential 缺 Secret 仍返回 400 且原凭据不变。首轮抓到的错误载荷现在仍应被后端拒绝，修复点是前端不再无意生成它。

### 结论

- 本轮新发现：0 条；当前无未解决 critical/important/minor。
- 最终差异复核：本轮只修默认类型应用与显式 PATCH 条件，并补组件/PG 回归，其他微软协议、Google 提取、身份、设备轮询和共享锁序未变化；前轮完整审查仍适用。重算 scope 与本轮一致，`git diff --check` 通过。
- 项目证据：最终前端全量 `302 passed`、账户 E2E `5 passed`、真实全栈 `8 passed` 日志已查证；前轮完整后端 `560 passed`、显式两家 Electron 定向 `39 passed` 与桌面/packaged 通过证据未被生产后端变更作废。本轮独立验证集中于修改范围，未重复冒充执行全部门禁。
- 七视角复核：安全与秘密边界无回退；正确性复验旧账户普通保存与显式升级；公开契约及配置传递无新变更；性能/资源和轮询退避保留；架构/共享生命周期与锁序保留；健壮性继续严格拒绝无 Secret 显式升级；文档/规格与新增/编辑语义一致。未发现新增可观测问题。
- 未进表提示：共享流程与账户 application 仍超过 400 行维护建议，高分支函数仍需持续维护；生成契约不计。真实外部应用注册/微软或 Google 登录/2FA/管理员同意未实测，符合 spec 有意不测，不把供应商夹具通过当作真实服务已连通。
- 系统性 follow-up：无。
- 总体判断：首轮 blocker 已由生产前端修复并经组件/真实 PG 复验，最终范围通过本轮代码审查。

### AC 复验方式

- AC-001：`re_verified` — 独立组件与 PG 旧账户回归确认原样保存/移组不隐式改型；新增/主动登录入口及已存客户端复用保留。
- AC-002：`re_verified` — 独立组件确认显式 confidential+Secret 升级载荷；PG 确认缺 Secret 显式升级仍拒绝，命名配置与缺项提示保留。
- AC-003：`re_verified` — 复查 Web/localhost 元数据与可信回调逻辑未变，前轮核查的生产 Electron 动态端口/无 Cookie 流程保留。
- AC-004：`re_verified` — 微软 authorization_code+PKCE、设备 grant、tenant 和最小委托权限代码未变，前轮独立请求测试证据保持有效。
- AC-005：`re_verified` — /me id/mail 与 inbox 可访问性核查未变，不解析 Token 或以 UPN 猜邮箱。
- AC-006：`re_verified` — 旧 Graph 身份建立、客户端/租户/远端 ID/精确邮箱匹配与重复邮箱拒绝未变，前轮独立 PG 证据保持有效。
- AC-007：`re_verified` — 共享 owner/epoch/供应商/用途/原子消费与最终保存锁序未变；轮询与 callback 只暂存结果。
- AC-008：`re_verified` — 错误分类、原凭据保护、Secret/Token 缓存合并与后台刷新行锁未变。
- AC-009：`re_verified` — 新增/编辑帮助文案与入口未变，本轮独立组件仍执行帮助步骤断言。
- AC-010：`re_verified` — Client ID 与自动取得 Refresh Token 的说明、设备短码操作语言及合法手动字段路径保留。
- AC-011：`re_verified` — Microsoft 仅 Graph，原 IMAP 拒绝与其他 IMAP 分支未回退。
- AC-012：`re_verified` — 独立两家旧账户组件/PG 回归确认分组变更、原凭据和隐式类型保持；秘密、URL 与移动布局代码未变，账户 E2E 通过日志已核查。
- AC-013：`re_verified` — 本轮独立组件继续覆盖设备码无回调/Secret、短码复制、链接和取消，服务端期限来源未变。
- AC-014：`re_verified` — next_poll_at/interval、pending、slow_down/429、跨进程锁和过期/迟到结果处理未变，前轮独立后端证据保持有效。
- AC-015：`re_verified` — 官方验证 URI 白名单、长码服务端保密、原会话最终确认及身份核对逻辑未变。
- AC-016：`re_verified` — 注册/策略失败指引、原 Client ID 与自动持续访问权限行为未变，帮助文案无回退。

coverage = 16 / 16 (100.0%)

verdict: PASS

## Round 3 (2026-10-24T23:48:47+08:00)

reviewed_scope: 42658742333b6b92

### Findings

本轮零 finding。

### 前轮结论与本轮差异复核

- f001 保持已消除；Round 2 代码审查及独立组件 27 passed、真实 PG 2 passed 证据继续适用。
- 本轮仅 `docs/specs_index.md:7` 将 account_connection 的 task 清单从 t053 补齐为 t053、t054、t055，与累计 spec 已交付内容一致。日期与其他索引行未变。
- 独立重算最终 scope 为本轮值；仅在内存将该索引行恢复至前轮内容后重算，结果精确等于 Round 2 的 `12e66374e938defc`，确认其余完整交付范围未变；未修改该文件或实现/测试。
- 本轮不重复代码测试，沿用 Round 2 全范围审查与最终门禁证据。七视角中，文档/规格索引关联现已补齐；安全、正确性、契约、性能/资源、架构、健壮性内容均未变化，无新增发现。
- 未进表提示与有意不测范围沿用 Round 2；不宣称完成真实供应商账号授权。
- 系统性 follow-up：无。
- 总体判断：索引补齐正确，完整最终交付内容保持已审查行为，本轮 PASS。

### AC 复验方式

AC-001 至 AC-016 均为 `re_verified`：通过前轮审查、独立测试及本轮完整内容指纹差分确认行为、证据未变；具体逐条证据见 Round 2 同名小节。本轮只新增 spec 索引关联核查，无新增或删改 AC。

coverage = 16 / 16 (100.0%)

verdict: PASS
