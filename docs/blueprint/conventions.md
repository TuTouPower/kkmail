# 约定 (Conventions)

模板流程的编号与 Markdown 格式见 `.repo_template/docs/usage.md`「命名与格式」。本文定义 kkmail 架构规范、安全基线与编码约定。

## 一、 核心安全与设计基线

1. **单用户 · UUID 即能力凭据 (Capability-based)**：
    - 实例无多租户角色或行级用户 ACL。
    - 在已认证的 Session / API Key 边界内，掌握资源 UUID 即可访问该资源；不得将其作为“多租户防 IDOR”缺陷处理。详见 `docs/guides/security.md`。
2. **邮件 HTML 渲染沙箱**：
    - 邮件 HTML 正文只能经由 `src/frontend/src/lib/mailBody.ts` 进行 DOMPurify 过滤；
    - 必须在带有 CSP 约束的无脚本 `iframe` 沙箱（`srcDoc`）中呈现；
    - 严禁使用 `dangerouslySetInnerHTML`。
3. **HTTP 传输与状态机**：
    - 前端写操作一律走 `src/frontend/src/api/client.ts` 的 `apiRequest` / `postJson`；
    - 不安全请求自动带 `X-CSRF-Token`，缺失立即 Fail-Closed；
    - 移动端 760px 响应式断点（`src/frontend/src/lib/viewport.ts`），导航统一走 Zustand store。
4. **密钥与凭据规范**：
    - 不预设弱口令或示例密钥，缺失时拒绝启动；
    - 凭据仅经 `CredentialStore` 存储并由 blob keyring 派生加密；
    - 日志与 `last_error` 必须经 `mail_core.security.redact` 脱敏。

## 二、 Schema 与类型落点

|类型|例子|落点|
|:---|:---|:---|
|**跨服务契约**|`OpenAPI` JSON 模式|`schemas/openapi.json`|
|**前端生成契约**|OpenAPI 生成的 TypeScript 接口|`src/frontend/src/api/generated/schema.ts`|
|**代码内契约**|Pydantic model、TypeScript 领域类型|后端跟模块走（`src/mail_core/api/`, `src/mail_core/mail/domain/`）；前端在 `src/frontend/src/api/schemaTypes.ts`|
|**数据库迁移**|Alembic 数据库版本脚本|`src/mail_core/db/alembic/versions/`|
|**环境配置模板**|环境变量说明与示例|`config/.env.example`（根目录保留 `.env.example` 软链）|

## 三、 原子写与状态防损

- 写入权威状态、派生索引（`docs/tasks_index.json`、`docs/pending/` 等）必须通过临时文件 + fsync + `os.replace` 原子替换，防止进程异常中断留下半写入文件。
- 工具链内部公共 helper：`from repo_task.documents import atomic_write_text`。
