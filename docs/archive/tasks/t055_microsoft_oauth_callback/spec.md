# Task spec

## 背景

用户明确要求 Microsoft 同时增加跳转回调与设备码登录，并用熟悉的 Google 登录解释两者。官方确认两条路径均可获得 Access Token 与 Refresh Token；Client ID 来自应用注册。用户无需手工提取令牌，后台自动处理持续同步所需的 offline_access。当前运行 DB 25 Graph、9 IMAP，未发现 Microsoft IMAP，用户确认无须迁移。

## 契约区

### 范围

- 为 Microsoft Graph 新增账户和既有 Graph 重新授权接通官方授权码登录/回调及设备码登录；复用 t054 会话绑定、短期状态与最终保存。
- 支持自托管网页与 Electron，个人 Outlook/Hotmail/Live 及公共云 Microsoft 365，配置 Client ID、Secret、租户及账号类型，完善对应帮助弹窗。
- 提供“浏览器登录”和“设备码登录”两个可理解入口；设备码展示微软验证地址与用户短码，后端按官方间隔轮询，无须配置回调地址。保留合法已有 OAuth 凭据的高级手动填写。

### 非范围

- 不实现 Microsoft IMAP/XOAUTH2、Exchange EWS、主权云、应用级 client_credentials 或证书认证。
- 不迁移历史邮件身份、不绕开邮箱唯一性、不增加旧 IMAP 兼容层；不代办 Entra 租户/外部应用注册、不创建或发布外部资源。
- 不新增发信、联系人或系统登录 SSO；邮件账号授权与 kkmail 本地登录保持独立。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：新增 Microsoft 账户提供“使用 Microsoft 登录”，编辑既有 Graph 账户提供“重新授权”；默认浏览器登录方式经微软官方授权端点跳转并回调；也可选择设备码登录，两种方式均自动取得 Refresh Token，正常路径不要求用户手工提取或粘贴 Token。已有 25 个 Graph 账户的已存 Client ID/客户端配置可复用，未经用户操作不强制重新授权。

- [ ] AC-002：用户可配置 Entra Application (client) ID、账号类型/租户及按客户端类型需要的 Client Secret；配置缺失时可打开对应帮助；浏览器回调方式显示准确回调 URI。公共客户端及设备码方式不要求 Secret；采用 Web 机密客户端的回调方式要求用户提供 Secret value，不能把 secret ID 当作 Secret。配置不硬编码，不借用第三方应用 ID。

- [ ] AC-003：网页使用登记的 Web HTTPS 回调和后端换码；Electron 通过系统浏览器使用原生客户端 loopback 回调，覆盖动态本地端口并按微软 localhost/127.0.0.1 实际登记规则处理，不能把 Google 的端口匹配规则直接套用到 Microsoft。最终返回原 Electron 账户表单，回调浏览器无应用 Cookie 时仍完成受约束暂存及原会话领取。

- [ ] AC-004：浏览器回调方式使用 authorization_code 与 PKCE S256；设备码方式使用官方 device_code grant，不套用回调的 state/PKCE 参数；基于 common / consumers / organizations / 明确租户匹配个人 Outlook 与 Microsoft 365 账号类型。申请 Graph 委托 Mail.ReadWrite、User.Read 和 offline_access，User.Read 仅用于读取并核对当前授权用户；不申请 Mail.Send、IMAP 权限、应用全邮箱权限或 client_credentials。

- [ ] AC-005：任一方式成功取得令牌后，后端经 Graph /me 核实服务商账号身份及邮箱，必要时确认其具有可访问邮箱；Access Token 作为不透明凭据，不解析其 JWT 猜邮箱或权限。新增以已核实邮箱保存为 graph；邮箱缺失或无邮箱时给出明确错误，不把任意显示名或未经核验的登录名当邮箱补入。

- [ ] AC-006：编辑重新授权绑定原 Graph 账号，校验同一微软用户及邮箱身份；选择另一账号、客户端或租户不符时不覆盖旧凭据。旧 Graph 未保存远端用户 ID 时，将新授权 /me 返回的真实邮箱与账户已存邮箱精确核对，通过后建立远端身份；旧凭据过期或撤销不阻止重新授权。邮箱或身份无法核对时明确失败，不能猜测或要求删除历史邮件。新增遇重复邮箱不默默转为编辑，不创建重复记录。

- [ ] AC-007：两种方式复用 t054 会话/epoch/供应商/用途绑定、原子消费、服务端暂存及最终确认保存；短期流程有效期不超过 10 分钟且不超过供应商返回的期限。非法 state、跨会话、跨供应商、重复回调或设备码结果消费、过期、取消、未登录领取均拒绝，不提前修改账户。不同账户并发授权互不串用；重试从新流程开始。

- [ ] AC-008：拒绝授权、关闭窗口、管理员未同意、租户/应用账号类型不匹配、回调不匹配、Secret 无效或过期、权限不足、缺 Refresh Token 和网络错误均展示脱敏原因及下一步指引。失败保留原 Graph 凭据；成功最终保存后正确轮换 Token 与清理旧缓存，不与后台刷新互相覆盖。

- [ ] AC-009：新增及编辑中的帮助图标均可打开微软凭据步骤：Entra ID → App registrations → New registration → 选择包含目标账号的账号类型 → Overview 复制 Application (client) ID → Authentication 根据方式配置（浏览器方式登记回调，设备码方式启用公共客户端流程）→ API permissions 添加委托权限 → 仅机密客户端创建并复制 Secret value → 回到 kkmail 选择对应登录方式，由应用自动保存 Refresh Token。说明 Entra 租户/应用注册权限、企业管理员同意等前置条件，不保证每个个人微软账号都能自行注册应用。

- [ ] AC-010：帮助明确区分：Client ID 来自注册；Refresh Token 由本产品完成登录授权后自动取得，不能在门户直接查看；已有合法 Refresh Token 可使用 t053 高级命名字段更新，仍受客户端与权限匹配校验。设备码帮助用用户能操作的语言说明“复制短验证码 → 打开微软官方验证页 → 输入代码并登录 → 返回 kkmail 等待确认”，不要求理解 grant、scope 或手工提取 Token，不提供抓包或第三方 Token 工具步骤。

- [ ] AC-011：Microsoft 新增和编辑仅呈现 Graph OAuth，所有 t053 定义的 Microsoft IMAP 拒绝规则继续生效，不因本 task 新增授权能力恢复任何 Microsoft IMAP/XOAUTH2 入口；不迁移邮件身份、不创建旧 IMAP 兼容分支、不改变其他供应商 IMAP。

- [ ] AC-012：回调、帮助、状态轮询与错误反馈在桌面和移动布局可使用；Secret/Token/授权码/校验器不进入日志、浏览器持久存储或 postMessage。回调处理完成后清理 URL 查询，重新授权后不改变账户分组、同步偏好或历史邮件。

- [ ] AC-013：新增和编辑均可选择“设备码登录”；使用用户配置且允许设备码流程的公共 Client ID 向官方 devicecode 端点申请短码，展示 verification_uri、user_code、实际剩余时间、“复制验证码”“打开微软登录页”和“取消”操作。该方式不要求回调地址、Client Secret 或额外监听本机端口；自托管网页和 Electron 均可用，Electron 使用系统浏览器。

- [ ] AC-014：后端根据返回的 interval 轮询 token 端点；authorization_pending 表示继续等待，不弹成失败，不允许每次前端刷新都发起额外轮询。供应商限流或 slow_down 时降低频率；用户拒绝、过期、无效代码、会话失效或取消后停止轮询并给出对应提示。有效期取供应商 expires_in 与本地流程上限中的较短值，多进程不会重复执行同一轮询，过期不能把迟到成功写入账户。

- [ ] AC-015：user_code 可返回原发起会话以供显示及复制，长 device_code 仅在服务端短期加密保存，不返回浏览器、不进入 URL或日志。验证地址必须来自微软官方受信端点，不依赖微软未提供的 verification_uri_complete，也不自行拼接带验证码的登录链接。设备码成功结果继续做 Graph 身份/邮箱核对、只允许原发起会话最终确认保存，不能绕过新增重复邮箱和编辑账号匹配规则。

- [ ] AC-016：设备码注册配置与组织策略不支持时明确展示设置步骤或拒绝原因，可由用户切换到浏览器登录，不自动使用其他 Client ID 或 Secret。帮助解释 Client ID 标识应用且可供多个邮箱授权，设备码与回调两条路径均自动申请“允许后台继续同步”，不把 offline_access 做成用户必须填写、勾选或额外购买的选项。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。生产授权请求、回调、身份核对和加密保存通过隔离假供应商与真实应用/DB验证；真实 Google/Microsoft 账号授权另作用户环境冒烟，未执行时必须明确说明，不把模拟成功报告为真实供应商已连通。

## 上下文区

- 来源：用户本轮明确增加设备码登录，并要求用 Google OAuth 对照解释微软流程；数据库范围已确认；核实日期 `2026-10-24`。
- 官方：[Entra 应用注册与 Client ID](https://learn.microsoft.com/en-us/entra/identity-platform/quickstart-register-app)、[授权码/PKCE/刷新](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow)、[回调登记与 loopback 限制](https://learn.microsoft.com/en-us/entra/identity-platform/reply-url)、[Graph 委托授权](https://learn.microsoft.com/en-us/graph/auth-v2-user)、[Graph /me 的 User.Read](https://learn.microsoft.com/en-us/graph/api/user-get?view=graph-rest-1.0)、[Mail.ReadWrite](https://learn.microsoft.com/en-us/graph/permissions-reference#mailreadwrite)、[官方设备码方式](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-device-code)、[公共客户端配置](https://learn.microsoft.com/en-us/entra/identity-platform/msal-client-applications)、[持续访问权限](https://learn.microsoft.com/en-us/entra/identity-platform/scopes-oidc#the-offline_access-scope)。
- 事实：微软官方 IMAP 仍支持 OAuth2；本项目按用户产品决策彻底下线 Microsoft IMAP，仅 Graph OAuth；不能把该决定写成“微软 IMAP 协议全面停用”。
- 当前实例只读统计：25 graph、9 imap，Microsoft 已知域名/host/供应商标识筛查为 0；Account.email 有唯一约束，无需处理存量 IMAP 到 Graph 的远端 ID 迁移。

### 有意不测

- 真实 Entra 应用创建、管理员同意、2FA 和真实微软账户授权成功：依赖用户权限和供应商账号；不擅自操作外部应用，真实验证需单独记录，不以请求桩冒充。

### 测试策略

- TDD：用真实 API/PG 与假 Microsoft authorization/token/Graph 端点覆盖个人/组织账号、租户、PKCE、code exchange、/me 身份、已有 Graph 无远端 ID、同邮箱不同用户、缺邮件地址、未带 Refresh Token、回调重放、并发流程和最终保存；设备码覆盖待授权/拒绝/过期/限流/取消、个人及组织账号、无回调配置成功、公共客户端未启用、长码保密、interval 遵守与迟到结果拒绝。
- 黑盒从新增/编辑帮助图标走到授权、回调、确认保存；验证原账户分组/邮件不变及错误后原凭据仍可用。对 Electron 系统浏览器和无 Cookie 回调、微软 localhost 端口/路径登记规则作独立测试；已有 Microsoft IMAP 拒绝回归不得删去。
- 执行 blueprint 门禁、接口生成核验及涉及桌面测试；真实第三方冒烟未完成时明确记录限制。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无未核实协议阻塞。普通个人微软账号能否注册自有应用取决于 Entra 租户和注册权限，不作为产品可保证事项；使用者须提供有效客户端登记，缺失时展示帮助。外部管理员策略、客户端登记及已授权账号状态不由代码伪造。

### 风险与回退

- 风险：误用微软账号类型/回调登记、网页登录与桌面公共客户端混淆、不同邮箱/租户凭据误覆盖、令牌泄漏及管理员策略拒绝。
- 回退：禁用微软跳转和设备码入口并取消未完成轮询并保留原 Graph 凭据与手动更新路径；回退执行提交，不清理账户或历史邮件，不恢复 Microsoft IMAP。

### 依赖与约束

- 硬依赖 t054，传递依赖 t053；复用已验证会话绑定与一次性结果存储，设备码有独立协议步骤但不复制第二套账户提交或秘密保存机制。
- Microsoft /me 需要 User.Read，帮助需解释此权限用途；Mail.ReadWrite 不包含发信，不额外申请 Mail.Send。
- 设备码使用允许公共客户端流程的注册，不以请求中增加 Secret 将机密客户端硬转成公共客户端；不要求设备码路径登记回调。
- 原生 loopback 登记按微软官方规则；localhost 的忽略端口规则不能假定适用于 127.0.0.1。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：Microsoft Graph 授权码/设备码及重新授权、短期轮询、/me 身份核对与客户端平台差异。
- `docs/blueprint/conventions.md`：Graph-only 供应商行为、应用配置与帮助规则、旧 Graph 凭据保留。
- `docs/blueprint/testing.md`：Microsoft 授权错误、设备码轮询/取消/过期、跨账号安全与桌面回调验证。
