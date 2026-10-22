# p010 远程图片拦截提示条未适配深色模式及前端未定义CSS变量与硬编码颜色扫描

- 现象：深色模式下打开包含远程图片的 HTML 邮件时，邮件正文上方的「远程图片已拦截（防追踪）。 仅此邮件允许加载」提示条背景呈刺眼的浅灰白色（`#f7f7f8`），文字颜色对比异常，且按钮为浏览器原生未修饰样式，破坏深色模式视觉一致性。
- 影响：深色模式下邮件阅读界面突兀失调；文字与背景对比度不合规；同时全工程存在多处引用未定义 CSS 变量（如重试按钮边框背景失效、右键菜单浅色回退等）及脱离设计系统的硬编码颜色（如深色模式菜单硬编码覆盖、浅色模式错误页误回退深色等）。
- 根因：
    1. 主点根因：`MessageReader.tsx` 第 182 行内联样式引用了未定义的 CSS 变量 `background: 'var(--panel, #f7f7f8)'`。由于 `tokens.css` 中未声明 `--panel`，浏览器无论在亮色还是暗色模式下均回退至浅色 `#f7f7f8`；且内联 button 未设置任何设计系统边框/背景/内边距/颜色等样式。
    2. 已确认同类位点（未定义 CSS 变量）：
        - `src/frontend/src/components/Sidebar.tsx:269-271`：重试按钮引用了未定义的 `--border`、`--card`、`--fg` 且无 fallback，导致样式完全失效；应使用 `--line`、`--surface-2`、`--text`。
        - `src/frontend/src/design-system/tokens.css:828`：`.context-menu` 引用了未定义的 `--panel-surface`（fallback 为 `#ffffff`）。
        - `src/frontend/src/components/SettingsModal.tsx:133`：引用了未定义的 `--yellow`（设计系统定义为 `--warning` / `--orange`）。
        - `src/frontend/src/components/ErrorBoundary.tsx:68`：引用了未定义的 `--bg`（设计系统定义为 `--canvas`）；在浅色模式下由于变量缺失会强制回退至深色 `#171819`。
    3. 已确认脱离设计系统/硬编码颜色位点：
        - `src/frontend/src/design-system/tokens.css:839-841`：`[data-theme='dark'] .context-menu` 硬编码了 `background: #25262b; border-color: #3b3d45;`，未走 `--surface` 与 `--line` 语义 Token。
        - `src/frontend/src/design-system/tokens.css:872`：`.context-menu-item.danger:hover` 硬编码了 `rgba(239, 68, 68, 0.12)`。
        - `src/frontend/src/components/SettingsModal.tsx:133`：警告背景硬编码 `background: 'rgba(234, 179, 8, 0.15)'`。
        - `src/frontend/src/components/ErrorBoundary.tsx:58-113`：fallback 全部写死暗色值（`#202124`、`#e8e8e8`、`#9a9a9a`、`#333`、`#ef4444`），破坏浅色模式容灾表现；主按钮高亮文字硬编码 `#fff`（应为 `--on-primary`）。
        - `src/frontend/src/components/MessageReader.tsx:196`：iframe 邮件正文背景硬编码 `background: '#fff'`，未接入 `tokens.css` 已声明的 `--mail-body` Token。
- 测试缺口：
    1. 前端单元测试 `MessageReader.test.tsx` 仅测试纯文本邮件（`body_type: 'text'`），缺少含 `<img src="https://...">` 的 HTML 邮件用例，未覆盖拦截条的存在性、解除逻辑及 DOM 语义。
    2. 缺乏针对前端源码中 CSS Token 有效性与硬编码颜色的静态检查机制，导致写错或未在 `tokens.css` 中定义的变量无法在构建/单测阶段被捕获。
    3. 补测建议：在 `MessageReader.test.tsx` 中增加外链图片拦截条渲染与「仅此邮件允许加载」交互测试，确保采用 `tokens.css` 语义化样式；补齐前端 CSS token 静态扫描或断言。
- 线索：`src/frontend/src/components/MessageReader.tsx:182`；`.scratch/reproduce.cjs`；`.scratch/scan_all_colors.cjs`。
- 处理：未开
