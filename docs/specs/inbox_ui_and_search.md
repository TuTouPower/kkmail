# 需求规格：收件箱交互、游标翻页与全文检索 (Inbox UI and Search)

## 背景

为用户提供现代化、高性能的三栏式邮件阅读体验，支持深翻页、全局未读角标展示、多语言即时检索与安全邮件正文沙箱渲染。

## 契约区

### 范围

- 聚合收件箱与单账户收件箱列表展示。
- 基于 `useInfiniteQuery` 与 Keyset 游标的“加载更多”列表翻页。
- 侧边栏对接服务端 `/api/mail/stats` 全局未读统计。
- 全文检索（PostgreSQL FTS + Trigram，支持 CJK 单字即时检索与英文防抖）。
- 邮件正文沙箱 iframe 渲染与附件下载。

### 非范围

- 撰写新邮件界面。
- 浏览器端多标签扩展。

### 验收标准

- [x] AC-001：侧边栏未读角标单次请求服务端全局聚合统计接口，各账户及统一收件箱未读数精准呈现，不依赖前端首屏缓存推导。
- [x] AC-002：邮件列表初始加载首屏（100 封），若存在后续邮件，列表底部呈现“加载更多”按钮；点击后平滑追加后续邮件，不发生全屏闪烁或覆盖。
- [x] AC-003：在列表内删除单封邮件时，通过乐观更新从当前多页列表中平滑移除，不导致列表重查归零显示空屏。
- [x] AC-004：搜索输入框支持 CJK 中文单字（`[\u4e00-\u9fa5]`）即时触发搜索，纯英文保持 250ms 防抖与 2 字符阈值；搜索结果支持翻页累加。
- [x] AC-005：邮件富文本正文必须经 DOMPurify 净化并在带有 CSP 约束的无脚本沙箱 iframe 中渲染，移除 `allow-popups-to-escape-sandbox`，所有外链自带 `rel="noopener noreferrer"`。
- [x] AC-006：侧边栏支持平滑折叠至图标栏；侧栏与列表间分割条支持鼠标连续拖拽调整宽度并持久化。

### 可测试性声明

全部 AC 可自动测试。

## 上下文区

- 来源：`docs/blueprint/decisions.md` (前端长列表游标分页与未读角标决策)

### 有意不测

- 像素级视觉微调与各种屏幕色彩还原（由设计系统 tokens 与组件单元测试约束）。

### 测试策略

- 前端组件测试：`src/frontend/src/components/MessageList.test.tsx`、`Sidebar.test.tsx`、`ColumnResize.test.tsx`。
- 浏览器端到端测试：`src/frontend/e2e/smoke.spec.ts`。

### 未知契约清单

无

### 风险与回退

- 风险：全局未读统计接口瞬时超时。
- 回退：前端优雅降级回各账户分别请求，不阻断主收件箱展示。

### 依赖与约束

- 依赖后端 `/api/mail/stats` 与 `/api/mail/inbox` 游标接口。

### Finalization 时更新的 blueprint

- `docs/blueprint/decisions.md`：前端长列表游标分页与未读角标。
- `docs/blueprint/conventions.md`：邮件 HTML 渲染沙箱与响应式布局约定。
