# p053 邮件列表顶部展示 [object Object] 红色错误信息

- 现象：用户进入邮件列表或页面获得焦点时，邮件列表上方出现红色 `[object Object]` 错误横条（渲染为 `<div role="alert" className="list-note error">[object Object]</div>`）。
- 影响：后台邮件增量同步（delta sync）及用户活跃心跳上报（activity heartbeat）因 CSRF 拦截完全失效，且向用户暴露无意义的 JavaScript 对象字符串化错误。
- 根因：
    1. CSRF 凭证缺失：`src/frontend/src/hooks/use_scope_sync.ts` 绕过了前端统一的 API 客户端（`postJson` / `apiRequest`），直接使用原生 `fetch` 发送 POST `/api/mail/sync/delta` 与 POST `/api/mail/sync/activity`，未携带 `X-CSRF-Token` 请求头。后端 `enforce_csrf` 拦截并返回 HTTP 403 `{"detail": {"error": "CSRF validation failed", "csrf_error": true}}`。
    2. 错误解析未防范对象：`use_scope_sync.ts` 中使用 `throw new Error(errData.detail || ...)`。当后端返回的 `detail` 为对象或数组（如 FastAPI 403 CSRF 错误结构或 422 验证错误）时，`new Error(obj)` 隐式调用 `String(obj)` 产生 `"[object Object]"`，导致捕获并传递到 UI 的 `scopeSyncError` 变成 `"[object Object]"`。
    3. 已确认同类位点：
        - `src/frontend/src/hooks/use_scope_sync.ts:26`：POST `/api/mail/sync/delta` 裸 `fetch` 且错误解析不规范（已确认）。
        - `src/frontend/src/hooks/use_scope_sync.ts:104`：POST `/api/mail/sync/activity` 裸 `fetch` 缺少 CSRF 头（已确认）。
        - `src/frontend/src/lib/actions.ts:8`：`errorMessage` 缺少对 `[object Object]` 和嵌套对象型 `detail` 的防御过滤（防御性同类位点）。
- 测试缺口：
    1. 前端单元测试（Vitest）：
        - `use_scope_sync.ts` 零单元测试覆盖。
        - `MessageList.test.tsx:741` 打桩 `fetch` 无条件返回 200 OK，未断言请求头是否携带 `X-CSRF-Token`。
        - 缺少对后端返回非字符串 `detail`（如对象/数组）时 UI 容错渲染的断言。
    2. 后端接口测试（pytest）：
        - `tests/mail_core/test_sync_requests.py:55` 仅使用 `Authorization: Bearer <API_KEY>` 测试，未在 Cookie Session 鉴权模式下测试 `/api/mail/sync/delta`。
        - `deps.py:53` 中 `api_key` 鉴权豁免 CSRF 校验，导致 CSRF 拦截逻辑未被测试覆盖。
    3. 前端 Mock E2E 测试（Playwright + stubApi）：
        - `stubApi.ts` 未注册 `/api/mail/sync/delta`，直接落入 404 fallback（返回字符串 detail 避开了对象转换）。
        - 缺乏全局网络错误监控和非预期错误条断言。
    4. 真实全栈 E2E 测试（full_stack.spec.ts）：
        - 邮件由后台 Worker 异步同步入库，前端列表渲染成功满足断言，但未断言页面不存在 `.list-note.error`。
    5. 应补层级与断言：
        - 前端单元测试：增加 `use_scope_sync.test.ts`，断言使用统一 client、正确附带 CSRF Token、正确解析对象型错误文案。
        - 组件与 E2E 测试：在 `MessageList.test.tsx` 和 E2E 流程中加入页面无 `.list-note.error` 且无未处理 fetch 失败的断言。
        - 后端测试：补充 Cookie session 下调用 `/sync/delta` 校验 CSRF 的 pytest 用例。
- 线索：`.scratch/reproduce_scope_sync_error.mjs`
- 处理：未开
