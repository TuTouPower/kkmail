# Task spec

## 背景

设置页添加和编辑账户目前只按 IMAP / Gmail API / Microsoft Graph 切换，OAuth 依赖手填凭据 JSON，IMAP 缺少供应商预设和独立登录名。用户要求按邮箱供应商定制两种界面，并核对各供应商接入要求。本 task 交付供应商表单、凭据帮助弹窗及 Microsoft IMAP 下线；完整 Google、Microsoft 跳转授权分别由 t054、t055 交付。

## 契约区

### 范围

- 覆盖 Outlook / Hotmail / Live / Microsoft 365、Gmail / Google Workspace、QQ / Foxmail 邮箱、网易 163 / 126 / yeah、iCloud、Yahoo、Zoho，以及其他 / 自定义 IMAP。供应商、协议、认证方式分开表达，添加和编辑复用同一套字段规则。
- 将 OAuth JSON 主路径替换为命名字段；补齐 IMAP 预设、登录用户名、供应商前置步骤和官方帮助。完善安全读取配置、凭据局部更新、校验及旧账户编辑。
- 添加和编辑均提供可点击帮助图标，按供应商及当前认证方式弹窗说明凭据获取步骤；移除 Microsoft IMAP 选择、连接路径和支持性文案，不保留兼容连接。
- Proton 地址显示 Bridge 与付费计划限制，不作为可直接连接的供应商；自定义域名允许手选实际供应商。

### 非范围

- OAuth 跳转登录与回调由 t054/t055 交付，本 task 不重复实现、不展示尚不可用的授权按钮；设备码授权同样由 t055 交付；不新增应用注册托管、IMAP XOAUTH2、Exchange/EWS、POP3 或 Proton Bridge 集成。
- 不支持 Microsoft 主权云或证书型应用认证；现有公共云 Graph 和用户委托 Refresh Token 路径保持范围。
- 不增加 SMTP、发信、联系人、通知；当前运行 DB 未发现 Microsoft IMAP，不增加历史账户兼容分支、跨协议迁移、重复邮箱绕过或邮件身份重建；不扩展导入工具。
- 不把成功保存宣称为远端连接验证成功；不新增连接测试端点。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [x] AC-001：添加账户可选择本 spec 供应商矩阵中所有直接支持项与“其他 / 自定义 IMAP”；仅显示当前供应商及接入方式所需连接和凭据字段，不要求填写凭据 JSON；编辑账户采用相同字段名、帮助和认证说明。

- [x] AC-002：新增账户按完整域名、忽略大小写给出供应商建议；如 `qq.com.evil.example` 不得识别成 QQ。自定义域名可手选 Gmail / Microsoft 365 / 其他供应商，用户明确选择优先；切换邮箱或自动建议不得覆盖手动填写的服务器和连接配置。

- [x] AC-003：选择 QQ/Foxmail、网易、iCloud、Yahoo 后按矩阵预填服务器、993 和 TLS，并展示准确凭据名称、客户端开通要求及官方帮助入口。IMAP 登录名默认完整邮箱且可修改，保存并重新编辑后保留；预设允许用户修改，编辑旧账户不得用预设覆盖已存服务器、端口、TLS 或用户名。

- [x] AC-004：Outlook/Microsoft 365 仅支持 Microsoft Graph OAuth，新增和编辑均不提供 Microsoft IMAP，高级手动凭据路径分别展示 Application (Client) ID、Refresh Token；公共客户端无需 Client Secret，用户声明机密客户端后要求填写 Client Secret。高级项可选择 common / consumers / organizations / 指定租户，生成对应公共云令牌端点；说明 ID Token 和短期 Access Token 均不能替代 Refresh Token，Graph 令牌所需权限不能由仅有 IMAP 权限替代。

- [x] AC-005：Gmail 提供 Gmail API 和 IMAP 应用专用密码两种接入方式。API 高级手动凭据路径展示 Client ID、Refresh Token、Client Secret 独立字段；手动新建必填 Client ID 和 Refresh Token，Client Secret 按已有客户端注册要求提供，不对所有 Gmail 账户强制必填；IMAP 使用 `imap.gmail.com:993`、TLS 与应用专用密码，提示需启用两步验证且组织策略或高级保护可能禁止生成应用密码，不提示个人 Gmail 仍需开启 IMAP，不引导使用普通登录密码。

- [x] AC-006：Microsoft Graph 帮助说明现有读信及状态写回需委托 `Mail.ReadWrite`，取得 Refresh Token 需 `offline_access`，组织账号可能受管理员策略限制；Gmail API 帮助说明需启用 Gmail API、匹配客户端和已授权的 `gmail.modify` 范围。不得额外要求 Graph `Mail.Send`、Gmail `gmail.send` 或 `https://mail.google.com/` 范围；不能宣称 `gmail.modify` 本身不含发送能力。

- [x] AC-007：Zoho 使用 IMAP，显示完整邮箱登录名及密码 / 应用专用密码，提示先启用 IMAP、账号计划和管理员限制；区分个人和付费企业配置，并提示数据中心决定实际主机，以账号内配置为准，不把 `.com` 主机强加给所有地区账户。

- [x] AC-008：其他 / 自定义 IMAP 可填写主机、端口、TLS、独立登录名和密码；不因无法识别域名阻止保存。识别到 Proton 公共邮箱域名时明确提示不能用 Proton 登录密码直连、需付费 Bridge 且本产品未集成，不生成虚构公网 IMAP 主机，不为此关闭私网地址防护或 TLS 证书验证。

- [x] AC-009：编辑始终以已存实际协议为准；已有 Graph/Gmail API 账号不受域名猜测干扰，Microsoft IMAP 不提供编辑连接或重新启用入口；当前 DB 无此类账户，本 task 不新增其兼容编辑逻辑。不能在编辑中静默切换协议；缺少供应商标识的历史账户可以打开、保留连接配置并修改分组，旧 JSON 凭据无须先迁移或重新输入。

- [x] AC-010：编辑响应只返回表单需要的白名单非敏感配置；密码、Refresh Token、Access Token、Client Secret 和原始凭据 JSON 永不回显。所有凭据输入初始为空，明确“留空保持不变”；仅修改分组或连接参数时原凭据完整保留。

- [x] AC-011：仅更新某个非空凭据字段时，服务端基于已存加密凭据合并，保留其余字段及未由本表单管理的既有字段；空输入不清除原值。新建或凭据变更时校验有效组合，缺失字段返回字段级脱敏错误；校验失败不写入半份账户、分组、配置或凭据变更。现有账户只改无关字段时不因旧凭据格式而强制重填。

- [x] AC-012：OAuth 客户端、Refresh Token、Client Secret、令牌端点或 scope 发生变更后，旧缓存 Access Token 和过期时间失效，后续刷新使用新有效组合；轮换后的 Refresh Token 继续经既有 CredentialStore 保存，不能被编辑请求中的旧快照覆盖。

- [x] AC-013：切换供应商或认证方式立即清除不适用的凭据草稿；提交载荷只包含当前方式允许字段，不夹带前一供应商密码、令牌或主机。关闭再打开表单不残留凭据；凭据不进入 localStorage、sessionStorage、URL、客户端持久缓存或错误日志。

- [x] AC-014：前端与 API 均拒绝当前方式所需字段缺失、非法端口、不支持的供应商与协议组合；保留 IMAP 主机 SSRF 限制及 OAuth HTTPS 令牌端点白名单，字段错误不包含提交秘密。编辑合法配置、分组变更及同步开关等既有行为继续可用。

- [x] AC-015：桌面和 760px 以下移动布局中，IMAP 与 OAuth 表单内容及帮助可阅读、长令牌输入不撑破窗口，提交操作可达；所有输入有可访问标签，原生 dialog 焦点约束、Esc/取消和关闭后的触发点焦点恢复保持有效。

- [x] AC-016：添加和编辑表单的当前认证方式旁均有带可访问名称的帮助图标；鼠标点击或键盘激活打开对应说明弹窗。内容随 Google IMAP、Google OAuth、Microsoft OAuth、QQ、网易、iCloud、Yahoo、Zoho 等切换，包含前置条件、分步操作和官方链接；关闭只恢复帮助图标焦点，不关闭账户表单、不清除草稿，Esc 先关闭最上层弹窗。

- [x] AC-017：Google IMAP 帮助明确指导“启用两步验证 → 生成应用专用密码 → 用于 IMAP 密码框”；Google OAuth 帮助说明“启用 Gmail API → 配置同意屏幕及测试用户 → 创建正确类型 OAuth 客户端 → 配置回调 → 登录授权”。Microsoft OAuth 帮助说明“Entra 应用注册 → 选择账号类型 → 复制 Application (client) ID → 按方式登记回调或启用设备码公共客户端 → 配置 Graph 委托权限 → 登录授权”，以用户语言说明登录完成后后台自动保存令牌，区分 Client ID、Client Secret value、secret ID、ID Token 和 Access Token；不要求普通用户抓包提取 Token，不指向第三方令牌获取站点。

- [x] AC-018：新增账户、连接配置更新、相关导入接入路径及 Worker/provider 构建均拒绝 Microsoft IMAP：包括明确 Microsoft 供应商品牌、已知 Microsoft 邮箱域名或 Microsoft IMAP 官方主机的组合；更换别名或通过“其他 IMAP”不能绕过既有可识别项。生产代码删除 Microsoft IMAP 预设、支持分支及旧“建议使用 Graph”软提示，不新增 XOAUTH2 回退。Google、QQ、网易和其他 IMAP 保持可用；此下线不删除账户或已存邮件。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。外部服务商的真实授权和登录成功不属于本 task AC；字段、校验、生产请求构造、加密持久化、编辑行为、布局和可访问性均使用隔离夹具验证。

## 上下文区

- 来源：本次用户明确要求创建 task；核实日期 `2026-10-24`。effective status 检查：主仓无登记 worktree，仅 main 本地分支；t051、t052 为文件夹行为，不与本需求等价，无须复用。
- 代码依据：`src/frontend/src/components/settings_account_form.tsx` 当前依赖凭据 JSON；`src/mail_core/providers/factory.py` 支持 imap/gmail/graph，IMAP 支持独立用户名；`src/mail_core/providers/oauth.py` 通过 Client ID + Refresh Token 刷新，Client Secret 按提供值发送；`src/mail_core/accounts/service.py` 当前凭据更新为整体替换，摘要尚不返回 IMAP 登录名。
- 最新用户确认：Google 同时保留 IMAP 与 OAuth，Google/Microsoft 均新增跳转回调；添加和编辑均适配并提供获取凭据帮助弹窗。三个交付按 t053 → t054 → t055 执行；均未 start。
- 当前实例只读核验：容器 `kkmail-mail-core-api` 使用的运行 DB，共 25 个 graph、9 个 imap；按 Microsoft 邮箱域名、IMAP host、供应商标识筛查，Microsoft IMAP 数量为 0。用户据此要求不考虑迁移。未输出账户地址或凭据，未修改 DB。

### 供应商矩阵与官方依据

以下为表单交付规则，主机为预设而非不可修改常量；均只涉及收信和现有远端状态写回。官方要求按 `2026-10-24` 核对，未使用真实用户凭据登录。

|供应商|现有接入方式与字段|服务器 / 前置条件|官方依据|
|---|---|---|---|
|Outlook / Hotmail / Live / Microsoft 365|本产品仅 Graph OAuth；t053 提供命名字段和步骤帮助，t055 接通登录回调自动取得令牌|Client ID 来自 Entra 应用注册，Refresh Token 来自授权码换取；微软官方 IMAP 仍支持 OAuth，但本产品移除 Microsoft IMAP 全部接入路径，不宣称协议已全球停用|[Outlook 设置](https://support.microsoft.com/en-us/outlook/pop-imap-and-smtp-settings-for-outlook-com)、[刷新与客户端类型](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-auth-code-flow#refresh-the-access-token)、[Graph 权限](https://learn.microsoft.com/en-us/graph/permissions-reference#mailreadwrite)|
|Gmail / Google Workspace|Gmail API OAuth，或 IMAP 应用专用密码；API 使用 Client ID、Refresh Token、按客户端类型需要的 Client Secret|API 启用及已有授权；IMAP 为 imap.gmail.com:993 TLS；应用密码需两步验证且受账号策略约束|[Web OAuth 凭据](https://developers.google.com/identity/protocols/oauth2/web-server)、[桌面 OAuth 凭据](https://developers.google.com/identity/protocols/oauth2/native-app)、[Gmail 范围](https://developers.google.com/workspace/gmail/api/auth/scopes)、[应用密码](https://support.google.com/accounts/answer/185833)、[个人 IMAP 常开](https://support.google.com/mail/answer/7126229)、[IMAP 设置](https://developers.google.com/workspace/gmail/imap/imap-smtp)|
|QQ / Foxmail 邮箱|IMAP；完整邮箱登录名、授权码|imap.qq.com:993 TLS；先开启 IMAP 并生成客户端授权码；Foxmail 指 @foxmail.com 邮箱，不指 Foxmail 软件内任意账户|[QQ 服务开关](https://service.mail.qq.com/detail/0/141)、[腾讯授权码说明](https://cloud.tencent.com/document/product/1270/55456)、[腾讯连接参数表](https://main.qcloudimg.com/raw/document/product/pdf/1270_46586_cn.pdf)|
|网易 163 / 126 / yeah|IMAP；邮箱登录名、客户端授权码|依次 imap.163.com、imap.126.com、imap.yeah.net；993 TLS；先开启客户端协议并生成授权码|[网易客户端协议帮助](https://help.mail.163.com/faq.do?m=list&categoryID=90)、[新增授权码](https://help.mail.163.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac286624f309a1a7089)、[官方服务器表](https://help.mail.163.com/faqDetail.do?code=d7a5dc8471cd0c0e8b4b8f4f8e49998b374173cfe9171305fa1ce630d7f67ac22b85ac2e7c90cd63)；服务器表以图片展示，创建时浏览器读取并核对|
|iCloud（icloud.com / me.com / mac.com）|IMAP；可修改登录名、应用专用密码|imap.mail.me.com:993 TLS；Apple 文档说明登录名可为邮箱前缀，连接不成功时使用完整地址；需生成应用专用密码|[Apple 服务器设置](https://support.apple.com/en-us/102525)、[生成应用密码与两步认证前置](https://support.apple.com/en-us/102654)|
|Yahoo|IMAP；完整邮箱登录名、应用专用密码|imap.mail.yahoo.com:993 TLS；应用密码可用性以账号安全设置为准|[Yahoo IMAP 设置](https://in.help.yahoo.com/kb/SLN4075.html)|
|Zoho|IMAP；完整邮箱登录名、密码或应用专用密码|个人常见 imap.zoho.com，付费企业常见 imappro.zoho.com；993 TLS；实际主机由数据中心及账号内设置决定，需开通 IMAP，部分免费计划不支持，2FA/SAML 使用应用密码|[Zoho 官方设置](https://www.zoho.com/mail/help/imap-access.html)|
|其他 / 自定义 IMAP|主机、端口、TLS、独立用户名、密码|按自托管或企业管理员提供值配置；不猜测 custom domain 的实际托管商|现有 `ImapProvider` 与 `build_provider` 契约|
|Proton（仅限制说明）|不提供直接公网连接配置|官方要求付费 Proton Mail Bridge；本 task 不集成，不默认放开 loopback/private host|[Proton 说明](https://proton.me/support/imap-smtp-and-pop3-setup)|

供应商品牌可以作为非敏感账户配置保存，实际 provider 仍以 imap / gmail / graph 路由。历史账户允许按实际 provider 与完整域名推断展示，不强制批量回填，不推断自定义域名托管商。

### 有意不测

- 真实供应商登录、短信/2FA、应用注册与管理员授权：需要外部账号及用户交互，不作为可自动重复门禁；不据请求桩宣称真实供应商已连通。
- Proton Bridge、IMAP XOAUTH2、Microsoft 主权云和证书认证：均在非范围内，仅验证范围提示。

### 测试策略

- TDD：先补新增/编辑表单参数化测试，再实现供应商矩阵；覆盖公共/机密客户端、合法和恶意相似域名、自定义域名、手填参数优先及跨供应商草稿清理。
- API/PG 测试触达真实 CredentialStore 加密保存与账户更新：读取无秘密、局部合并、空值不清除、失败事务回滚、旧账户仅改分组、OAuth 缓存失效和刷新轮换不丢失。协议请求桩验证实际 factory / OAuth 刷新请求，不能只测试表单自造映射。
- 浏览器 E2E 覆盖创建 IMAP、创建 Graph、编辑 Gmail 凭据、Microsoft IMAP 拒绝、移动宽度布局及焦点恢复。旧测试语义失效时新增新语义测试；旧测试保留或整体删除并写理由，禁止直接改预期迁就实现。
- 执行期按 `docs/blueprint/testing.md` 运行相关后端、前端测试、类型/构建门禁和黑盒验证；API 契约改动后从源重新导出 OpenAPI 并生成前端类型。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无阻塞本范围的未核实外部契约。认证字段、端点、权限与预设依据见上表；供应商账号具体能否授权、应用密码生成资格及企业管理员策略属于外部账号状态，不承诺跨账号通用可用。
- 不把填写 scope 当成取得权限：新 scope 不能扩大 Refresh Token 原授权；表单说明需在供应商侧完成匹配授权。令牌按不透明字符串处理，不通过解析 JWT 猜测供应商、账号或权限。

### 风险与回退

- 风险：品牌误判覆盖旧连接或漏拦 Microsoft IMAP；凭据部分更新丢失未修改字段；旧 Access Token 掩盖新凭据错误；编辑与后台令牌轮换互相覆盖；企业策略导致字段正确仍认证失败。
- 回退：在 task 分支恢复表单和账户更新变更；不执行数据删除或协议转换。若实现需要破坏性存量迁移，先验证可恢复备份及回退路径并另行确认范围，不在此 task 默认授权内。

### 依赖与约束

- 无硬依赖；t051/t052 处理 IMAP 文件夹语义，可独立开展。潜在文件冲突：t051/t052 可能修改 provider 测试，实施前按实际 diff 核对，不为此预设硬依赖。
- 本 task 包含鉴权凭据与协议契约，使用 full review。复用 CredentialStore、已有 apiRequest/CSRF、SSRF 与 TLS 安全边界；不将 Client Secret、Token 放入公开配置、日志或测试快照。
- Microsoft IMAP 检测按本产品明确支持的品牌、已知域名及规范化官方主机处理；不声称可凭任意自定义域名离线发现实际托管商，不扩大到主动网络自动发现。
- 不预设共享 Client ID、Client Secret 或默认 token，不创建外部应用；全部凭据由用户提供。若需要新增数据库列或模型改动必须配套 Alembic 迁移；优先复用现有 JSON config，避免无必要迁移。

### Finalization 时更新的 blueprint

- `docs/blueprint/conventions.md`：设置工作区增加供应商字段规则、凭据获取帮助弹窗、Microsoft IMAP 下线、旧账户推断、凭据局部更新与不回显约束。
- `docs/blueprint/architecture.md`：账户供应商品牌与 provider 路由、配置白名单及 CredentialStore 更新边界。
- `docs/blueprint/testing.md`：新增供应商矩阵、凭据更新与浏览器账户表单验证入口。
