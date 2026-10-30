---
tid: "t067"
slug: "reader_isolated_html_endpoint"
title: "邮件正文独立隔离渲染端点与切断父级CSP继承"
status: "dropped"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "消除 srcdoc 强制继承父页面 CSP 导致的放行图片被拦截问题；正文改为独立 URL 端点并独立设置 CSP，守住主站零出网基线，补齐真实全栈外链图片解码测试; dropped: 原独立正文端点方案存在XFO阻断、Electron强制覆盖及双重净化mXSS技术债，按Opus 5.5审查结论废弃，改走服务端图片代理路线"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 创建期事实与复现：用户在生产环境放行发件人后，Google 邮件内的外链图片依然碎图。用真实 Chromium 复现捕获底层报错 `Loading the image 'https://www.gstatic.com/...' violates directive: "img-src 'self' data: blob:"`。
- 根因与方案决策：`srcdoc` 强制继承父页面 CSP 且不可放宽。将邮件正文改造为独立 HTTP 浏览上下文的渲染端点，由后端下发正文专属 CSP，主应用 `_SPA_CSP` 保持最严格的 `img-src 'self' data: blob:` 零外部出网安全基线不变。同时补齐挂载真实中间件的 Playwright 外链图片解码自动化验证。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round N (YYYY-MM-DDThh:mm:ss+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t000_code_f001|critical/important/minor|已修/遗留/撤回|一句话|文件:行 / pNNN / tid|

无 finding 时写“Round N 零 finding”。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足 / 未满足
- 测试：待执行时填写
- 黑盒：待执行时填写
- review：待执行时填写
- AC 证据：见 `handoff.json`

### 结果摘要

- 待执行时填写；遗留只写引用，不复制正文
