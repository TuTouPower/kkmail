# kkmail 前端 (Frontend)

基于 React + TypeScript + Vite 开发的单页应用 (SPA)，用于接入 kkmail 后端 mail-core。

## 开发与构建

```bash
# 从仓库根目录执行：需确保后端 mail-core 已启动（默认 127.0.0.1:8000）
cd src/frontend
npm ci
npm run dev          # 启动开发服务器（http://127.0.0.1:5173），/api 代理转发至 mail-core
npm run build        # 生产打包输出：dist/（生产镜像中由 mail-core 同源托管）
npm test             # 执行 Vitest 单元测试与 OpenAPI 漂移校验
```

可选配置：当页面源与 API 源不一致时，可设置 `VITE_API_BASE`（或运行时 `__KKMAIL_CONFIG__.apiBase`）。系统推荐并默认使用同源托管。

## `src/` 目录结构

|目录路径|职责说明|
|---|---|
|`api/`|HTTP 请求客户端、mail-core 辅助函数与 OpenAPI 自动生成类型|
|`components/`|核心界面组件：Sidebar（侧栏）、MessageList（邮件列表）、MessageReader（阅读器）、Settings（设置）、Login（登录）|
|`hooks/`|自定义 Hooks：SSE 实时事件流 (`useMailCoreRealtime`)、作用域同步与权威轮询 (`use_scope_sync`)|
|`public/theme_bootstrap.js`|首屏预渲染主题引导脚本，在应用挂载前由 `index.html` 加载|
|`store/`|Zustand 全局 UI 状态管理|
|`design-system/`|设计系统 CSS Tokens 与主题变量|
|`lib/`|核心工具库：mailKey 缓存键计算、DOMPurify/srcdoc 沙箱过滤、视口响应式断点等|

系统架构边界与产品范围详见 [ARCHITECTURE.md](./ARCHITECTURE.md)。关联文档：[docs/guides/deployment.md](../../docs/guides/deployment.md)、[schemas/openapi.json](../../schemas/openapi.json)、[DESIGN.md](../../DESIGN.md)。
