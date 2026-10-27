# 前端架构规范 (kkmail SPA)

kkmail 的 React + TypeScript + Vite 单页应用架构。由后端 mail-core 在同源路径（`/`）下托管提供，或由 Electron 桌面主进程加载。

## 架构原则

- **统一客户端，唯一后端**：所有 HTTP 请求统经 `src/api/client.ts`（支持 Cookie Session、CSRF 校验与超时控制）；邮件列表、详情与 SSE 逻辑收敛于 `src/api/mailCore.ts`；禁止在浏览器端直接请求第三方提供商 API。
- **自动生成 OpenAPI 类型**：`src/api/generated/schema.ts` 由 `schemas/openapi.json` 生成（执行 `npm run openapi:gen`）；业务 DTO 在 `schemaTypes.ts` / `queries.ts` 中封装供 UI 消费；通过 `npm run openapi:check`（由 `npm test` 自动运行）保证类型与后端强一致。
- **服务端状态与 UI 状态分离**：TanStack Query 统一管理账号、分组、收件箱列表、搜索与邮件详情等服务端状态；Zustand (`src/store/mailStore.ts`) 管理本地主题、选区、侧栏与列表拖拽宽度、移动端视图及设置面板开关。
- **设计 Token 纪律**：布局与色彩 Token 定义在 `src/design-system/tokens.css`（参考根目录 `DESIGN.md`）；严禁在组件中硬编码临时十六进制颜色。
- **不包含发信与撰写**：产品范围严格排除写信 (compose)、回复 (reply)、转发 (forward)、联系人管理与系统推送；禁止重新引入相关界面。

## 界面拓扑与布局

`App.tsx` 提供三栏式外壳：`Sidebar`（侧栏）· `MessageList`（邮件列表）· `MessageReader`（阅读器），宽屏支持 `ColumnResize` 分割条连续拖拽调节宽度。视口宽度低于 `MOBILE_MAX_WIDTH`（760px，`src/lib/viewport.ts`）时，侧栏自动转为抽屉，列表与阅读器通过 `data-mobile-view` 切换展示。设置面板打开时覆盖右侧列表与阅读器工作区（`SettingsModal.tsx`）。

## 实时事件推送 (Realtime)

`useMailCoreRealtime` 通过 Cookie 认证在 `/api/events` 打开持久化 SSE 流，并在收到特定领域事件时精确失效对应的 TanStack Query 缓存。由于浏览器原生的 `EventSource` 不支持自定义 Authorization 头，事件流完全依赖 Session Cookie 认证。

## 工程脚本

|脚本命令|职责说明|
|---|---|
|`npm run dev`|启动 Vite 开发服务器；自动反向代理 `/api` 至 mail-core|
|`npm run build`|`tsc -b` 类型检查 + 生产打包输出至 `frontend/dist`|
|`npm test`|执行 Vitest 单元测试与 `openapi:check` 契约校验|
|`npm run openapi:gen`|重新生成 `src/api/generated/schema.ts` 类型定义|

## 永久排除项（禁止恢复）

- 遗留 Flask 模板 `templates/` / `static/`、浏览器扩展、外部多皮肤系统；
- 双运行 Flask 与 mail-core 的实验性特性开关。
