---
tid: "t011"
slug: "ui_reference"
title: "UI 稳定编号与引用复制"
status: "done"
branch: "t011_ui_reference"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "7a1f6280a717da31ae985d7f7cbf930da3709f02"
depends_on: ""
conflicts_with: ""
note: "用户批准：仅稳定编号、复制引用、按编号搜索源码；快捷键 Ctrl/Cmd+Shift+."
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 结构与元数据：在 `src/frontend/src/lib/uiReference.ts` 中建立固定编号注册表 `UI_ELEMENT_REGISTRY` 与快捷键解析器 `isUiReferenceShortcut`；在登录、侧栏、列表、阅读器、设置五大分区核心组件通过 `data-ui="XXNN"` 显式声明固定编号。
2. 浮层与交互：在 `src/frontend/src/components/UiReferenceOverlay.tsx` 中建立全局覆盖层，在捕获阶段拦截 `Ctrl/Cmd + Shift + .` 开关引用模式，动态扫描并测量可见目标浮动气泡；点击气泡复制静态结构化引用并触发反馈；捕获阶段优先消费 `Esc` 单独关闭引用模式。
3. 验证与门禁：补充 `uiReference.test.ts` 与 `UiReferenceOverlay.test.tsx` 单元测试；通过全套前端构建、打包冒烟与 Playwright E2E。更新 `docs/blueprint/conventions.md` 与 `docs/blueprint/testing.md`。

## Review 处置

无 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部通过
- 测试：前端单元 (183 passed), 桌面打包冒烟 passed, 后端全量 (381 passed)
- 黑盒：`npm --prefix src/frontend run test:e2e` (3 passed), `python3 scripts/run_full_stack_e2e.py` (3 passed)
- review：general PASS / overall PASS
- AC 证据：见 `handoff.json`

### 结果摘要

- 登录、侧栏、邮件列表、邮件详情与设置五大分区可独立修改元素均具备固定 `data-ui="XXNN"` 显式编号；
- 全局支持通过 `Ctrl/Cmd + Shift + .` 开启/关闭引用模式，`Esc` 独立退出模式；
- 点击气泡复制标准格式纯文本引用 `[UI:XXNN] 区域 · 描述`，不泄露任何运行时敏感内容；
- 编号与源码全局唯一对应，支持直接通过 `rg` 命令行快速反查源码模板位置。
- AC 证据：见 `handoff.json`

### 结果摘要

- 待执行时填写；遗留只写引用，不复制正文
