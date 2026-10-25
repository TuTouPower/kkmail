# p056 Microsoft 账户添加默认平铺复杂 OAuth 开发者选项且缺少配置时报错阻断

- 现象：在添加账户弹窗中选择邮箱供应商为“Microsoft / Outlook / Microsoft 365”时，连接方式为“Microsoft OAuth / Graph”，界面平铺展开大量底层 OAuth 开发者选项（OAuth 应用类型、Microsoft 登录方式、租户类型、回调地址、Client ID、Refresh Token、Client Secret、高级 OAuth 配置等）。选项繁杂，用户直接点击“使用 Microsoft 登录”时表单直接抛出红色内部术语报错：“缺少 OAuth 配置项：Client ID、Client Secret、可信回调地址 (MAIL_CORE_PUBLIC_ORIGIN)”。虽然界面顶部存在“如何获取凭据”按钮，但位置与报错脱节，且帮助弹窗说明为大段生硬技术文本，缺乏清晰步骤引导。
- 影响：自托管环境下普通用户无法直观添加 Outlook / Hotmail / Microsoft 365 邮箱；面对复杂的 Entra ID / OAuth 开发者术语感到困惑；未配置凭据时操作受阻且缺乏清晰引导。
- 根因：
    1. 认证机制与产品实现：微软自 2024 年 9 月起全面弃用 Basic Auth（普通密码与应用专用密码），全面强制现代身份验证（Modern Authentication / OAuth 2.0）。调用 Microsoft Graph API 同步邮件必须获取含 `Mail.ReadWrite` 权限的 OAuth 2.0 Access Token 与 Refresh Token（用户记忆中的“ID token 登录”实为基于 OIDC/OAuth 的现代验证流程；单纯的 ID Token 仅包含身份声明，不能用于调用 Graph 邮件同步 API）。
    2. 开发者配置与终端用户登录混杂：表单将 Azure Entra ID 应用注册的技术参数（客户端类型、登录方式、租户、回调地址、Secret）平铺给终端用户，未区分“自托管管理员/开发者配置”与“普通用户登录”，导致选项极度繁复。
    3. 缺乏极简流程推荐：未对自托管环境提供最简路径推荐（例如：自托管 Web 环境下最轻量的“公共客户端 + 设备码登录”，无需配置公网回调域名与 Client Secret，只需 Client ID 即可通过官方 devicelogin 页面授权）。
    4. 报错与引导脱节：报错信息展示硬编码环境变量名 `MAIL_CORE_PUBLIC_ORIGIN`，且报错区域本身无法直接唤起凭据获取说明；帮助弹窗步骤缺乏结构化、易于操作的指引。
- 同类位点清单：
    - `docs/pending/todo/p055_google_account_onboarding_ux_and_default_provider.md`：Google 账户添加同样存在默认平铺 OAuth 开发者表单且报错阻断的问题。
    - `src/frontend/src/components/settings_account_form.tsx:334-383`：Microsoft OAuth 表单平铺与校验阻断。
- 测试缺口：
    - 前端组件测试（`microsoft_account_form.test.tsx`、`provider_account_form.test.tsx`）均在预设完整 mock 凭据下测试通过，缺少对“初始未配置凭据状态”下表单引导、校验提示及交互路径的断言。
    - 应补层级：前端单测断言未配置凭据时的引导呈现、报错交互按钮响应、以及推荐模式的默认交互。
- 线索：`.scratch/reproduce_microsoft_oauth_form_ux.mjs`
- 处理：未开
