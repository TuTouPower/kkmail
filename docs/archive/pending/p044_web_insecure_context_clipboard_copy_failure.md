# p044 非安全上下文 Web 环境下剪贴板复制失败且无降级

- 现象：在 Docker 等自托管 Web 环境通过 HTTP（非 localhost/127.0.0.1 且非 HTTPS，即非安全上下文 Insecure Context）访问 kkmail 时，点击邮件发件人、收件人或邮箱地址等复制入口，弹出错误提示「复制失败：当前环境不支持剪贴板写入。请手动选择并复制地址」，无法复制到剪贴板。
- 影响：自托管 Web 用户通过局域网 IP / 域名 HTTP 访问时，全局所有复制能力全部瘫痪（包括 CopyAddress 邮箱地址、UiReferenceOverlay 界面编号、ErrorBoundary 诊断报告导出、settings_account_form OAuth 回调与验证码复制）。
- 根因：
    - 核心机制：现代浏览器安全策略（W3C Clipboard API 规范）规定 `navigator.clipboard` 仅暴露于 Secure Context（`window.isSecureContext === true`，如 HTTPS 或 localhost/127.0.0.1）。当通过 HTTP IP 访问时，浏览器环境下 `navigator.clipboard` 为 `undefined`。
    - 前端缺少降级：前端 `CopyAddress`、`UiReferenceOverlay`、`ErrorBoundary` 与 `settings_account_form` 等组件均直接判断 `!navigator.clipboard?.writeText` 并立即抛错或返回失败反馈，未提供针对非安全上下文的传统 DOM 复制降级（基于隐藏 `textarea` + `document.execCommand('copy')`）。
    - 已确认同类位点清单：
        1. `src/frontend/src/components/CopyAddress.tsx`（`copyAddress` 行 47-49，发件人/收件人/侧栏/设置邮箱复制）
        2. `src/frontend/src/components/ErrorBoundary.tsx`（`copyReport` 行 78-80，诊断日志复制）
        3. `src/frontend/src/components/UiReferenceOverlay.tsx`（`copyRef` 行 136-138，UI 编号标签复制）
        4. `src/frontend/src/components/settings_account_form.tsx`（行 345、360，OAuth 授权回调地址与设备码复制）
- 测试缺口：
    - 前端单元测试（如 `CopyAddress.test.tsx`、`ErrorBoundary.test.tsx`、`UiReferenceOverlay.test.tsx`）在 jsdom 环境下将 `navigator.clipboard = undefined` 时直接断言“呈现失败提示”视作通过，将降级缺失下的失败反馈误当成正常行为，未验证兜底降级流程；
    - 端到端测试（`tests/e2e/smoke.spec.ts`）在 `localhost` 下运行并显式授予 `clipboard-write` 权限，处于安全上下文，未覆盖局域网 HTTP 非安全上下文访问场景。
    - 应补测层级：在前端工具层/组件层增加针对无 `navigator.clipboard` 场景下成功降级调用 `document.execCommand('copy')` 的单元测试；并在真实非安全上下文（或模拟无剪贴板 API）下验证降级复制成功与不可用时的失败反馈。
- 线索：`.scratch/reproduce_clipboard_insecure_context.mjs`、`.scratch/verify_browser_lan.mjs`、`.scratch/verify_browser_fallback.mjs`
- 处理：fix-p044
