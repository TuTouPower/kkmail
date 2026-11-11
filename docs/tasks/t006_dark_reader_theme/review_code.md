# Task review t006（reviewer_focus: 代码）

- task：`t006_dark_reader_theme`
- spec：`docs/tasks/t006_dark_reader_theme/spec.md`
- diff_anchor：`7d7a5b3d915b94d200f252ad17425345b1be632f`
- target：`git -C '<local-path>' diff 7d7a5b3d915b94d200f252ad17425345b1be632f`
- round：1
- reviewed_at：2026-10-22T19:15:00+08:00

reviewed_scope: 4ec6f59d51f6f2e2

## Findings

Round 1 零 finding。

## 结论

- 前轮 finding 复核：首轮无前轮
- 本轮新发现：0 条
- 未进表的提示：无
- 总体判断：代码严格遵循 Apple Mail 设计规范实现三栏深色层级、文字/图标对比度与发件人 600 字重；CSS 聚焦选中与失焦选中规则准确，不影响侧栏与设置面板；消除全工程扫描出的全部 7 处未定义 CSS 变量，健全了静态检查与负向校验测试；正文深色适配采取保守分类策略，显式浅色富文本以独立纸张卡片隔离，DOMPurify、CSP 和 iframe 沙箱安全红线未做任何放宽。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：`re_verified`，查验 `src/frontend/src/design-system/tokens.css` 及 `assets/DESIGN.md`，三栏背景、边框、列表悬停、未读点、主次辅文本与图标精确匹配色值，发件人字重 600，`src/frontend/src/design-system/darkTheme.test.ts` 断言通过。
- AC-002：`re_verified`，查验 `tokens.css` 中的 `.message-list:focus-within .message-row.selected` 与 `.message-row.selected`，聚焦背景 #0A60FE、文字 #FFFFFF、时间副标题 #D0E2FF；失焦背景回退 #323236，选择对象不变。
- AC-003：`re_verified`，查验 `src/frontend/src/lib/mailBody.ts` 与 `src/frontend/src/components/MessageReader.tsx`，无配色 HTML 与纯文本采用 #1A1A1C 底色与可读文字，固定浅色富文本采用独立白底卡片承载，主题切换即时响应。
- AC-004：`re_verified`，查验 `MessageReader.tsx`、`Sidebar.tsx`、`SettingsModal.tsx`、`ErrorBoundary.tsx`、`tokens.css`，未定义变量 `--panel`、`--border`、`--card`、`--fg`、`--yellow`、`--bg`、`--panel-surface` 全部替换为语义 Token，亮暗模式均具备可读文字与一致背景边框。
- AC-005：`re_verified`，查验 `MessageReader.tsx` 中 `loadRemoteImages = Boolean(selectedKey && allowedRemoteImagesKey === selectedKey)` 与放行按钮交互，切换邮件默认拦截，CSP 与 sandbox 保持有效。
- AC-006：`re_verified`，运行 `node src/frontend/scripts/check_css_tokens.mjs` 及 `src/frontend/src/lib/checkCssTokens.test.ts`，负向夹具注入未定义变量时准确报错并指出文件与行号，全项目静态扫描通过。

coverage = 6/6 = 100%

verdict: PASS
