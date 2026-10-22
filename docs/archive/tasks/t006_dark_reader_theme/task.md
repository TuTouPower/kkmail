---
tid: "t006"
slug: "dark_reader_theme"
title: "统一深色阅读体验与语义颜色"
status: "done"
branch: "t006_dark_reader_theme"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "7d7a5b3d915b94d200f252ad17425345b1be632f"
depends_on: ""
conflicts_with: ""
note: "来源 p010、p012；合并主题与样式交付"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. **CSS 变量静态检查与负向夹具 (AC-006)**：
   - 建立 `src/frontend/scripts/check_css_tokens.mjs` 与 `src/frontend/src/lib/checkCssTokens.ts`；
   - 编写 `checkCssTokens.test.ts` 包含负向测试夹具与项目静态扫描断言；已接入 `npm test` 门禁。
2. **修复未定义变量与脱离设计系统位点 (AC-004)**：
   - 修复 `Sidebar.tsx` 重试按钮未定义的 `--border`、`--card`、`--fg` 为 `--line`、`--surface-2`、`--text`；
   - 修复 `SettingsModal.tsx` 警告未定义的 `--yellow` 为 `--warning`；
   - 修复 `ErrorBoundary.tsx` 全页错误未定义的 `--bg` 为 `--canvas` 并移除硬编码暗色回退；
   - 修复 `tokens.css` 上下文菜单 `--panel-surface` 为 `--surface`，移除硬编码色；
   - 修复 `MessageReader.tsx` 提示条 `--panel` 为 `--surface-2` 并修饰放行按钮。
3. **Apple Mail 原生深色色阶与聚焦选中规则 (AC-001, AC-002)**：
   - `tokens.css` 对齐深色三栏（侧栏 `#1E1E1E`、列表 `#212124`、阅读容器 `#1A1A1C`、边框 `#2C2C2E`、悬停 `#2A2A2E`、未读点 `#0A84FF`、主文本 `#FFFFFF`、次级 `#E4E4E6`、辅助 `#8E8E93`、图标 `#98989D`、悬停 `#FFFFFF`、发件人字重 600）；
   - 实现 `.message-list:focus-within .message-row.selected` 聚焦样式（背景 `#0A60FE`、文字 `#FFFFFF`、时间副标题 `#D0E2FF`）与失焦回退 `#323236`；
   - 同步更新 `assets/DESIGN.md`。
4. **正文深色适配与独立纸张卡片 (AC-003, AC-005)**：
   - `mailBody.ts` 实现 `classifyMailHtml` 保守分类与基于主题的 `buildMailSrcdoc`，CSP 与 DOMPurify 安全红线严格保持；
   - `MessageReader.tsx` 针对固定浅色富文本在深色模式下以 `.mail-paper-card` 独立白底纸张卡片隔离呈现，主题切换即时响应；
   - 拦截外链图片默认提示，放行仅对当前邮件生效，切换邮件重置拦截。
5. **门禁与验证**：
   - 前端单元测试 32 个测试套件（161 个测试）全部通过；
   - 前端类型检查 `tsc -b` 与生产打包 `npm run build` 全部成功；
   - E2E 冒烟测试 `npm --prefix src/frontend run test:e2e` 全部通过；
   - 模板契约测试与后端测试全部通过。

## Review 处置

Round 1: 0 finding（PASS）。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：PASS（全部 AC 达成并通过独立代码及测试双路审阅）
- 测试：`pytest .repo_template/tests -q -m contract` (148 passed)、`pytest tests/mail_core -q` (217 passed)、`(cd src/frontend && npm test && npx tsc -b && npm run build)` (161 passed, build ok)、`(cd src/desktop && npm test)` (ok)
- 黑盒：`npm --prefix src/frontend run test:e2e` (3 passed, 4.8s)
- review：`review_code.md` PASS、`review_test.md` PASS (`reviewed_scope: 4ec6f59d51f6f2e2`)
- AC 证据：见 `handoff.json`

### 结果摘要

- 统一深色阅读体验对齐 Apple Mail 原生三栏与色阶对比；
- 消除全工程 7 处未定义 CSS 变量，建立构建与测试静态 Token 扫描门禁；
- 纯文本与无配色 HTML 深色自适应，固定浅色富文本以独立白底纸张卡片隔离呈现；
- 保持 DOMPurify、无脚本 iframe、严格 CSP 与外链图片放行安全隔离。
