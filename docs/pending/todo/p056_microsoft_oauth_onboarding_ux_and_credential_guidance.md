# p056 Microsoft 账户采用内置公共 Client ID 与重定向链接换 Token 极简授权方案

## 1. 现象与现场复现

在添加账户弹窗中选择邮箱供应商为“Microsoft / Outlook / Microsoft 365”时，连接方式为“Microsoft OAuth / Graph”：

1. **表单平铺大量开发者选项**：界面平铺展示“OAuth 应用类型”（公共客户端/机密客户端）、“Microsoft 登录方式”（浏览器登录/设备码登录）、“Microsoft 账号类型/租户”（common/consumers/organizations）、“OAuth 回调地址”、“Client ID”、“Refresh Token”、“Client Secret”、“高级 OAuth 配置”（令牌端点、已授权范围）等。
2. **未配置时点击登录抛出硬编码内部错误**：用户在未自行配置 Azure 开发者应用的情况下，点击“使用 Microsoft 登录”，前端硬编码阻断并抛出红色报错：
    `缺少 OAuth 配置项：Client ID、Client Secret、可信回调地址 (MAIL_CORE_PUBLIC_ORIGIN)。请补齐配置或点击「如何获取凭据」查看步骤。`
3. **获取凭据引导与交互割裂**：顶部“如何获取凭据”按钮位置脱节，弹出的文字是一大段生硬晦涩的 Azure Entra ID 注册技术文档，没有提供符合普通用户使用习惯的步骤引导；在报错区域本身无法直接唤起有效操作。

## 2. 影响范围

- **所有自托管部署场景**：在没有配置公网可信 HTTPS 域名（`MAIL_CORE_PUBLIC_ORIGIN`）或没有企业 Azure 开发者凭据的自托管环境下，普通用户无法正常添加个人（`@outlook.com`、`@hotmail.com`、`@live.com` 等）或组织微软邮箱。
- **严重增加心智负担**：普通终端用户被强迫面对 OAuth 架构术语（公钥/私钥、租户、回调路由、Secret、端点等），交互体验极差。

## 3. 根因分析

1. **认证协议与机制**：微软自 2024 年 9 月 16 日起全面废止 Basic Auth（密码与应用密码登录 IMAP），强制执行现代身份验证（OAuth 2.0 / Modern Auth）。通过 Microsoft Graph API 同步邮件必须获取包含 `Mail.ReadWrite` 权限的 OAuth 2.0 `access_token` 与后台续期所需的 `refresh_token`（单纯的 ID Token 仅用于 OIDC 身份认证，无法调用 Graph 邮件同步 API）。
2. **缺乏开箱即用的公共客户端支持**：
    - 知名开源客户端（如 Mozilla Thunderbird）及上游项目（`assast/outlookEmail`）均内置了经过微软注册的**公共客户端 Client ID**（如 `9e5f94bc-e8a4-4e73-b8be-63364c29d753` 等标准公共应用 ID）。
    - **公共客户端流程（Public Client Flow）遵循 RFC 6749 规范，天生不需要 Client Secret**。
    - 当前 kkmail 强行要求用户自行提供 Client ID 和 Client Secret，且把 Web 环境判定为机密客户端并强校验公网 HTTPS 回调地址，完全阻断了自托管普通用户。
3. **未采用无公网域名的重定向链接换码机制**：
    - 上游项目早已实现“复制重定向 URL 换 Token”机制：即使本地没有运行公网服务器或回调监听，只要将重定向地址设为标准回环（如 `http://localhost:8080`），用户在微软页面同意授权后浏览器跳转至该地址，用户只需复制地址栏中的完整 URL 粘贴回表单，后端即可从中提取 `code` 并换取 `refresh_token`。

______________________________________________________________________

## 4. 修复实施方案（方案 A：极简公共客户端 + 重定向 URL 换 Token）

实施方案包含公共 Client ID 内置、授权 URL 构造、后端换码 API、前端极简交互状态机四大部分。

### 4.1 内置公共 Client ID 与参数规约

- **默认公共 Client ID**：后端配置内置默认微软公共应用 ID：
    `DEFAULT_MICROSOFT_CLIENT_ID = "9e5f94bc-e8a4-4e73-b8be-63364c29d753"`（支持环境变量 `MICROSOFT_CLIENT_ID` 覆盖，并允许高级用户在前端自定义）。
- **默认重定向地址**：`DEFAULT_MICROSOFT_REDIRECT_URI = "http://localhost:8080"`。
- **权限范围 (Scopes)**：
    `https://graph.microsoft.com/Mail.ReadWrite https://graph.microsoft.com/User.Read offline_access`。
- **免除 Secret 要求**：公共客户端模式下，后端与前端完全移除对 `client_secret` 的必填校验。

### 4.2 授权跳转链接生成逻辑

前端点击「使用微软授权登录」时，直接生成微软官方 OAuth 授权 URL：

```text
https://login.microsoftonline.com/common/oauth2/v2.0/authorize?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}&response_mode=query&scope={ENCODED_SCOPES}&state={RANDOM_STATE}&login_hint={USER_EMAIL}&prompt=select_account
```

- 若用户已输入邮箱地址，自动填入 `login_hint`，用户跳转至微软页面无需重复键入邮箱；
- 浏览器弹窗或在新标签页打开该 URL。

### 4.3 后端重定向链接换取 Token API（详细规格）

新增专有换码接口，负责解析用户粘贴的 URL 并兑换凭据落库：

- **路由**：`POST /api/accounts/oauth/exchange-redirect-url`
- **请求 Schema (`ExchangeRedirectUrlRequest`)**：
    ```python
    class ExchangeRedirectUrlRequest(BaseModel):
        redirected_url: str          # 用户粘贴的完整跳转 URL
        email: str | None = None     # 预期的邮箱地址（可选，用于一致性校验）
        group_id: str | None = None  # 所属分组 ID
        client_id: str | None = None # 可选，自定义 Client ID，留空使用内置公共 ID
    ```
- **后端执行步骤**：
    1. **URL 解析与错误校验**：
        - 使用 `urllib.parse.urlsplit` 与 `parse_qs` 解析 `redirected_url`；
        - 若包含 `error` 参数（如 `access_denied`、`interaction_required`），抛出可读异常：“微软授权失败：{error_description 或 error}”；
        - 若缺少 `code` 参数，抛出 400 异常：“链接中未找到授权码 (code)，请确保复制的是授权完成后的完整地址”；
    2. **换取令牌 (Token Exchange)**：
        - 向微软令牌端点发送 POST 请求：
            - 端点：`https://login.microsoftonline.com/common/oauth2/v2.0/token`
            - 数据：
                ```json
                {
                  "client_id": effective_client_id,
                  "grant_type": "authorization_code",
                  "code": auth_code,
                  "redirect_uri": DEFAULT_MICROSOFT_REDIRECT_URI,
                  "scope": "https://graph.microsoft.com/Mail.ReadWrite https://graph.microsoft.com/User.Read offline_access"
                }
                ```
        - 捕获微软返回的 `refresh_token`、`access_token`；
    3. **身份核验与邮箱获取**：
        - 使用取得的 `access_token` 调用 `GET https://graph.microsoft.com/v1.0/me`；
        - 取得微软账号真实主邮箱（`mail` 或 `userPrincipalName`）；
        - 若入参提供了 `email` 且与微软返回的主邮箱不匹配，抛出提示或以微软真实邮箱为准；
    4. **账户持久化**：
        - 创建或更新账户记录，`provider="graph"`，`credentials` 存储 `client_id`、`refresh_token` 等必要字段；
        - 触发首次账号组织刷新与排队同步任务。

### 4.4 前端极简交互与状态机流转

#### (1) 表单初始状态（极简输入）

- 界面仅展示：
    - **邮箱地址**（输入框，如 `myname@outlook.com`）；
    - **所属分组**（下拉选择）；
    - **主操作按钮**：【微软授权登录】（带有微软品牌图标的蓝色主按钮）；
    - **高级选项（折叠 `details`）**：默认收起，内含“自定义 Client ID”与“自定义重定向 URI”（仅供有自备 Azure 应用的高级开发者修改）。
- 彻底**移除**平铺的“应用类型（公共/机密）”、“租户（common）”、“Client Secret”、“Refresh Token”等输入框；
- 移除因未配置 `MAIL_CORE_PUBLIC_ORIGIN` 而阻断点击的校验。

#### (2) 授权与换码流程状态（用户点击后）

点击【微软授权登录】后，在新窗口打开微软登录页，弹窗界面就地切换为引导换码面板：

- **步骤引导提示**：
    1. 在已打开的微软窗口中登录您的 Outlook 邮箱并同意授权；
    2. 授权完成后，页面会跳转到一个打不开的网址（例如 `http://localhost:8080/?code=...`）；
    3. **复制浏览器地址栏的完整网址**，粘贴到下方输入框：
- **输入区域**：
    - `<textarea>` 或 `<input>`：占位符 `请粘贴地址栏中的完整重定向链接...`；
    - 【换取 Token 并添加】主按钮（调用 `POST /api/accounts/oauth/exchange-redirect-url`）；
    - 辅助操作：【重新打开授权页面】、【返回上一步】。
- **异常展示**：若用户粘贴格式错误或授权超时，直接在输入框下方以醒目红字给出清晰友好的中文说明，而非内部环境变量报错。

______________________________________________________________________

## 5. 代码改动清单

### 后端改动

- `src/mail_core/accounts/microsoft_oauth.py`：
    - 定义 `DEFAULT_MICROSOFT_CLIENT_ID` 与 `DEFAULT_MICROSOFT_REDIRECT_URI`；
    - 增加 `parse_redirect_code(redirected_url: str) -> str` 辅助解析函数；
    - 增加 `exchange_redirect_url_for_tokens(redirected_url: str, client_id: str | None) -> dict` 函数。
- `src/mail_core/api/oauth_routes.py`：
    - 增加 `POST /api/accounts/oauth/exchange-redirect-url` 路由及处理逻辑。
- `src/mail_core/accounts/connection.py`：
    - 调整 `validate_connection`，公共客户端允许空 `client_secret`。

### 前端改动

- `src/frontend/src/components/settings_account_form.tsx`：
    - 供应商为 `microsoft` 时，重构渲染结构为“极简发起态”与“粘贴 URL 换码态”；
    - 隐藏 Secret、应用类型等输入项；
    - 移除 `MAIL_CORE_PUBLIC_ORIGIN` 阻断逻辑；
    - 对接 `exchange-redirect-url` 接口完成提交。
- `src/frontend/src/lib/account_providers.ts`：
    - 更新 Microsoft 的帮助步骤与提示文案为简明 3 步说明。

______________________________________________________________________

## 6. 测试缺口与补测清单

1. **后端单测与集成测试**：
    - 增加 `test_parse_redirect_code`：测试合法 URL、带 state 的 URL、带 error 的 URL（如 `access_denied`）、完全缺失 code 的非法 URL 的解析断言；
    - 增加 `test_exchange_redirect_url_api`：使用 mock 微软 token 端点和 me 端点，测试成功换取 token 并创建账户的完整 API 链路；
    - 测试环境变量 `MICROSOFT_CLIENT_ID` 覆盖生效性。
2. **前端组件测试**：
    - 在 `microsoft_account_form.test.tsx` 中新增“重定向链接换码”模式测试；
    - 断言初始界面只展示邮箱、分组与授权按钮；
    - 断言点击授权后切换至引导换码面板；
    - 断言粘贴重定向 URL 后点击提交能正确调用换码 API 并反馈成功/失败。

- 线索：`.scratch/reproduce_microsoft_oauth_form_ux.mjs`
- 处理：未开
