# p055 Google 账户仅保留应用专用密码接入并重构添加流程与引导

- 现象：在添加账户弹窗中选择邮箱供应商为“Google / Gmail”时，连接方式默认选为“Google OAuth / Gmail API”，界面展示大量复杂的底层 OAuth 字段（Client ID、Client Secret、回调地址、端点等），点击后报内部配置缺失错误；用户无法直观以 16 位应用专用密码快速接入。
- 影响：面对自托管与个人使用场景，强制平铺未过审的 Google OAuth 增加了极高使用门槛与困惑，导致普通用户无法顺畅添加 Gmail 账户。
- 决策与整改目标：
    1. 架构与产品收敛：Google 供应商彻底移除复杂自建 OAuth/Gmail API 模式，**仅保留并全面支持「IMAP 应用专用密码」这一种方式**。
    2. 极简表单设计：
        - 切换到 Google / Gmail 时，连接方式锁定/默认选为 `IMAP（应用专用密码）`，彻底隐藏所有 OAuth 开发者字段（Client ID / Secret / Redirect URI / Token Endpoint 等）。
        - 用户可见字段极简为两项：邮箱地址 + 16 位应用专用密码。
        - 服务器参数（`imap.gmail.com`、993、SSL）由系统后台自动预置，默认隐藏或收纳于“高级网络设置”。
    3. 凭据获取教程重构：
        - 清除 `CredentialHelp` 中关于 Google Cloud Console、OAuth 审核、CASA 等所有冗余陈旧教程。
        - 更新为精准的 3 步指南：① 登录 Google 账号开启两步验证；② 进入应用专用密码生成页（直接提供 `https://myaccount.google.com/apppasswords` 官方直达链接）；③ 生成 16 位密码并填入 kkmail。
- 根因：前端未结合自托管产品定位做供应商接入策略收敛，将商业客户端适用的 OAuth 理念直接平铺为复杂的开发者表单，掩盖了开箱即用的应用专用密码路径。
- 同类位点清单：
    - `src/frontend/src/components/settings_account_form.tsx`：Google 选项及 OAuth 渲染分支清理。
    - `src/frontend/src/lib/account_providers.ts`：Google 供应商定义、连接方式与帮助步骤文本。
    - `src/frontend/src/components/credential_help.tsx`：帮助弹窗渲染与指引链接。
- 测试缺口：
    - 前端缺少 Google 供应商开箱即用（选 Google 仅展示邮箱与应用专用密码，提交直接创建 IMAP 账号）的组件单测与 E2E 验证。
    - 应补测试：断言选择 Google 时表单无任何 OAuth 字段、正确预填 Gmail IMAP 参数、密码框提示“应用专用密码”、帮助弹窗内容正确直达 Google App Passwords。
- 线索：`.scratch/reproduce_google_account_form_ux.mjs`
- 处理：fix/review-20261026-commits
