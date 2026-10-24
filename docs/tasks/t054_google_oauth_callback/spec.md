# Task spec

## 背景

用户明确要求增加 Google OAuth 跳转登录与回调；现有 OAuthTokenClient 仅刷新已有令牌，无授权码换取、短期流程存储或回调。交付网页与 Electron 均可新增 Google 账户、重新授权 Gmail API 账户的完整流程，并为 t055 复用已经验证的会话绑定和一次性结果。

## 契约区

### 范围

- Google Gmail API 授权码跳转、回调、离线凭据获取、真实邮箱核对、最终保存与重新授权；Google IMAP 继续由 t053 的应用密码表单处理。
- 必需的短期 OAuth 流程状态、PKCE、防重放、跨进程持久化、部署回调配置、系统浏览器返回及对应 UI/帮助。

### 非范围

- 不实现 Microsoft 授权（由 t055 交付），不迁移 IMAP 邮件身份，不新增发信或 Gmail IMAP XOAUTH2。
- 不创建外部 OAuth 应用、不发布应用或代办审核，不采用已弃用 OOB 手动复制授权码；不引入推测性插件式授权平台。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：Google 新增账户选择 OAuth 后可点击“使用 Google 登录”，已有 Gmail API 账户编辑时可点击“重新授权”；Google IMAP 的应用专用密码路径保持可用。登录入口创建真实授权请求并跳转 Google 官方页面，用户不必手工复制 Refresh Token。
- [ ] AC-002：授权前可配置用户自有 Client ID、匹配客户端类型的 Client Secret，以及可复制的实际回调 URI；编辑可复用已有加密客户端配置，空秘密字段不清除原值。缺配置时明确列出所缺项并可打开帮助；Google API 未配置不得阻止其他 IMAP 使用，前端不打包共享 Secret。
- [ ] AC-003：自托管网页使用后端处理授权码的 Web 客户端与已登记固定回调；HTTPS 公网 origin 来自可信部署配置，不从未受信 Host、Forwarded 或客户端 return URL 构造。桌面原生客户端采用系统浏览器及 127.0.0.1 loopback，正确处理动态端口；远程网页部署不把回调指向用户电脑 loopback，URL 查询参数不能伪造桌面模式。
- [ ] AC-004：授权请求使用 code 流程及 PKCE S256，申请 gmail.modify 和离线访问；按需重做同意以取得 Refresh Token，不请求 gmail.send 或 mail.google.com 全量范围。缺少所需授权范围或新建未取得可刷新的凭据时不允许保存为已授权；不将 Google 测试模式令牌说明为永不过期。
- [ ] AC-005：发起、查询状态、取消和最终保存只允许已登录的原始 kkmail 会话操作，写请求继续执行 CSRF。每次流程绑定会话身份、session_epoch、供应商、用途（新增/编辑）、目标账户和客户端配置，随机 state 与 code_verifier 仅服务端保存，有效期最长 10 分钟。跨会话、退出登录、epoch 失效、超时和取消后的流程不能领取或写入凭据。
- [ ] AC-006：回调仅接受已发起且未消费的匹配 state 与授权码；错误 provider、篡改 state、缺 state、缺 code、重复/并发回调以及授权码复用均失败关闭。流程状态跨 API 进程可读取且原子消费；不能因负载均衡到另一进程而失效或重复换码。
- [ ] AC-007：桌面系统浏览器不拥有 Electron 登录 Cookie 时，回调仍可通过有效 state/PKCE 完成后端换码并暂存结果；回调只暂存，不凭回调请求直接新增或改写账户。结果只能由发起流程的已认证应用领取和确认保存，不因 callback 路由无 Cookie 而放开整个 API 鉴权。
- [ ] AC-008：后端调用 Google token 端点交换 code，并使用 Gmail users.getProfile 核实实际授权邮箱；新增使用服务商返回的真实地址，重复邮箱返回明确冲突且不覆盖既有账户。编辑已有 Gmail API 账号时只能重新授权同一邮箱，不因 login_hint 或用户手填地址而接受另一账号，也不把 IMAP 账户直接切为 Gmail API。
- [ ] AC-009：成功回调在网页和 Electron 显示可恢复的授权成功状态，返回添加/编辑表单并保留所属分组与非敏感草稿；只有最终“添加/保存修改”才原子保存账户与加密凭据并使一次性授权结果失效。授权后取消表单不留下新账号或更换旧凭据；刷新/重复保存不产生重复账户。
- [ ] AC-010：令牌、Client Secret 和 code_verifier 不返回前端、不进入 URL/浏览器持久存储、postMessage 或日志；状态 API 只返回流程状态、已核实邮箱等白名单字段。回调含 code/state 的查询字符串不写访问日志；处理后清理地址并使用 no-store、no-referrer，页面不加载第三方资源，固定返回地址防止开放重定向。
- [ ] AC-011：用户拒绝、关闭授权窗口、弹窗被拦截、过期、网络错误、redirect_uri_mismatch、invalid_client、缺少权限或离线凭据时均展示脱敏可操作错误，可取消和重新发起；失败不覆盖已有账户、原凭据或其他尚有效流程。重新授权返回未带 Refresh Token 时仅允许对已确认相同客户端及邮箱保留旧有效 Refresh Token。
- [ ] AC-012：重新授权保存后后续同步使用新凭据；令牌缓存与原凭据按有效组合更新，保存、编辑、后台刷新并发时不会用旧快照覆盖新 Refresh Token。多个账户或多个同时授权流程相互隔离，不能把 A 的凭据保存到 B。
- [ ] AC-013：Google 帮助弹窗在新增和编辑均可打开，说明 Gmail IMAP 应用密码步骤、OAuth Web/桌面客户端区别、实际回调 URI 注册、Gmail API/同意屏幕/测试用户配置、测试模式常见 7 天有效期和组织策略；提供官方链接，明确个人部署也需自有应用配置，授权按钮本身不会代办注册或应用验证。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。生产授权请求、回调、身份核对和加密保存通过隔离假供应商与真实应用/DB验证；真实 Google/Microsoft 账号授权另作用户环境冒烟，未执行时必须明确说明，不把模拟成功报告为真实供应商已连通。

## 上下文区

- 来源：用户本轮要求“需要添加谷歌oauth跳转登录回调”，核实日期 `2026-10-24`；复用 t053 供应商表单与帮助。
- 官方：[Google Web 授权码与 offline access](https://developers.google.com/identity/protocols/oauth2/web-server)、[Desktop PKCE 与 loopback](https://developers.google.com/identity/protocols/oauth2/native-app)、[Gmail profile 邮箱](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users/getProfile)、[scope](https://developers.google.com/workspace/gmail/api/auth/scopes)、[令牌期限与测试模式](https://developers.google.com/identity/protocols/oauth2/)。
- 代码：`src/mail_core/providers/oauth.py` 仅提供 Refresh Token grant；`src/mail_core/api/deps.py`/`security/auth.py` 为会话与 CSRF 边界；`src/desktop/main.js` 已拦截外链并用系统浏览器，`startup.js` 支持动态本地端口。当前 requirements 无现成 OAuth 专用库，实现前评估成熟库与现有依赖，避免自行重造协议安全细节。

### 有意不测

- 外部账号登录、短信/2FA、同意屏幕审核及真实 Google 账号授权成功：依赖用户应用配置和第三方状态，不使用个人账号执行自动回归；需要另行记录真实环境结果。

### 测试策略

- 先红后绿覆盖真实 API/DB、假供应商 HTTP 端点及生产 code exchange/getProfile/save 路径；验证 state/PKCE、原子消费、多进程、取消、session_epoch 变化、身份不符、重复邮箱、缺 Refresh Token、令牌轮换和事务回滚。
- 浏览器黑盒跑 OAuth 新增和重新授权、Google IMAP 帮助及移动端；桌面用独立实例确认系统浏览器无应用 Cookie 仍可回调、动态端口和焦点恢复，不以 BrowserWindow 参数单测代替桌面流程证据。
- 按 blueprint testing 门禁运行后端、前端、涉及桌面测试和黑盒；接口从源导出 OpenAPI，新增 DB 模型须附 Alembic 迁移。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无未核实外部协议。官方已确认 Web/桌面授权码、PKCE、offline access 和 loopback 支持。真实环境的用户 Client ID/Secret、发布 origin、供应商应用登记和测试用户名单由操作者提供；缺失时功能显示配置指引，不能捏造默认凭据或冒充完成真实授权。

### 风险与回退

- 风险：登录 CSRF、code/state 重放、未认证桌面回调绑定错误、开放重定向、跨邮箱覆盖、短期秘密泄漏和令牌轮换丢失。
- 回退：禁用 Google 跳转入口并保留既有加密凭据与 Google IMAP；回退执行提交，数据库迁移按可回退方案处理，不清除既有邮件/账户。

### 依赖与约束

- 硬依赖 t053；t055 依赖本 task 的已实现授权流程，无须另建空泛基础设施 task。
- 网页后端为机密客户端，桌面为公共客户端；仅在受信本地 loopback 回调上容许 HTTP，不影响远端 IMAP 私网/证书防护。
- 短期流程最小化保存，过期可清理；新 DB 模型带迁移，秘密使用现有加密边界，用户自有客户端配置不入库到 Git。

### Finalization 时更新的 blueprint

- `docs/blueprint/architecture.md`：Google 授权码、短期流程与账户最终保存边界、网页/桌面回调。
- `docs/blueprint/conventions.md`：state/PKCE、会话绑定、令牌不回显与帮助弹窗。
- `docs/blueprint/testing.md`：OAuth 假供应商、重放/跨会话测试和桌面真实交互门禁。
