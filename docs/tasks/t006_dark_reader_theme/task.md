---
tid: "t006"
slug: "dark_reader_theme"
title: "统一深色阅读体验与语义颜色"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "来源 p010、p012；合并主题与样式交付"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

创建依据：p010、p012（2026-10-22 核实：MessageReader.tsx:182/196、Sidebar.tsx:269–271、SettingsModal.tsx:133、ErrorBoundary.tsx:68、tokens.css:828 等仍存在；扫描得到 --panel / --border / --card / --fg / --yellow / --bg / --panel-surface 七个未定义变量。tokens.css 深色三栏仍为旧色、--mail-body 仍为白色。MessageReader 组件测试仅有纯文本正文，mailBody.test.ts 已覆盖底层图片 CSP，但缺组件放行与主题场景。无等价 effective task。）

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

尚未开始 review，无 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：尚未实施
- 测试：待执行时填写
- 黑盒：待执行时填写
- review：待执行时填写
- AC 证据：见 `handoff.json`

### 结果摘要

- 待执行时填写；遗留只写引用，不复制正文
