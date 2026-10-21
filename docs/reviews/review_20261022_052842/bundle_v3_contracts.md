# Intensive Review — 视角3 契约、类型与接口规范 (Contracts, Typing & Breaking)

## 视角摘要

类型契约与 optionality、API/配置/Schema 兼容性、分层边界契约、DTO 校验。

## Findings

- [High][98] src/mail_core/api/accounts.py:24 — 路由层直接导入并消费 ORM 存储模型击穿分层架构契约 — `api/accounts.py` 第 24 行直接 `from mail_core.mail.storage.models import Account, AccountGroup`，且在 `_account_out` 中直接操作 ORM 实体字段并手动管理事务；违反了 `src/mail_core/README.md`「api: Routes call the application layer only」与分层架构契约 — 在 application 层定义标准数据传输对象（DTO），由 application 层统一完成 ORM 到 DTO 转换，路由层仅消费 application 层返回的数据。
- [High][90] src/frontend/src/lib/mailBody.ts:40 — iframe 沙箱缺少 allow-popups-to-escape-sandbox 导致 Web SPA 模式下外部链接无法正常浏览 — `MAIL_IFRAME_SANDBOX` 仅声明 `allow-popups`，未声明 `allow-popups-to-escape-sandbox`。在纯 Web SPA 浏览器访问模式下，由沙箱 iframe 内 `<base target="_blank">` 打开的外部新标签页强制继承 iframe 沙箱标记，导致新窗口禁止运行 JavaScript、禁用表单提交，访问外部网站时脚本全部失效 — 区分桌面环境与浏览器环境，或在 Web 模式下声明 `allow-popups-to-escape-sandbox`，或在 iframe 内拦截点击通过 postMessage 请求主窗口统一代理跳转。
- [Medium][95] src/frontend/src/lib/mailBody.ts:36 — base 标签滥用 rel 属性无法防止 opener 泄露且缺失 Referrer-Policy — `buildMailSrcdoc` 生成 `<base target="_blank" rel="noopener noreferrer">`。HTML 规范规定 `<base>` 仅支持 `href` 与 `target` 属性，浏览器解析时完全忽略其 `rel` 属性，且不会将其传递给内部 `<a>` 标签。DOMPurify 默认过滤掉 `target`，外链打开时无法通过 `<base>` 保障 `noopener`。同时 head 内未设置 `<meta name="referrer" content="no-referrer">`，正文外链点击存在 Referer 泄露风险 — 在 `buildMailSrcdoc` 的 `<head>` 中添加 `<meta name="referrer" content="no-referrer">`，并通过 DOMPurify 的 `afterSanitizeAttributes` 钩子为所有 `<a>` 标签强制写入 `target="_blank"` 和 `rel="noopener noreferrer"`.
- [Medium][90] src/frontend/src/lib/mailBody.ts:12 — DOMPurify 依赖标签黑名单过滤而非 USE_PROFILES 禁用 XML 命名空间 — `sanitizeMailHtml` 仅通过 `FORBID_TAGS` 列举 `['svg', 'math', ...]`，未启用 `USE_PROFILES: { html: true }`。对于 MathML/SVG 的嵌套标签（如 `<annotation-xml>`、`<foreignObject>`）未完全剥离命名空间，存在潜在 mXSS 绕过风险 — 在 DOMPurify 参数中加入 `USE_PROFILES: { html: true }`，从词法级别阻断非 HTML 命名空间元素。
- [Low][95] src/frontend/src/api/mailCore.ts:87 — 前端手写契约类型与 OpenAPI 生成类型重复存在漂移风险 — `AccountInboxStatsOut` 与 `GlobalStatsOut` 在 `mailCore.ts:87-96` 中手写定义，未复用 `schemaTypes.ts` 中由 `generated/schema.ts` 派生的标准类型 — 从 `schemaTypes.ts` 统一导出 OpenAPI 生成类型，删除手写同名接口。
- [Low][80] src/mail_core/api/app.py:80 — 中间件函数类型注解引用未导入的 Request — 第 80 行 `async def trace_id_middleware(request: Request, call_next):` 使用了 `Request`，但在文件顶部第 11 行 `from fastapi import Depends, FastAPI, Response` 中并未导入 `Request`。运行时内省工具调用 `typing.get_type_hints` 时将抛出 `NameError` — 在顶部 import 中显式加入 `Request`。
