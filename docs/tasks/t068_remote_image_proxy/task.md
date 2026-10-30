---
tid: "t068"
slug: "remote_image_proxy"
title: "外链图片服务端安全代理与防追踪防护"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "基于 d003 确立的架构决策，建立服务端安全图片代理（Image Proxy）彻底消解 CSP 继承死锁；主站与正文 CSP 统一定格为 'self' data: 零外部出网，实现工业级防追踪与真实外链图片解码渲染"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 创建期事实与决策：
    1. 实测确证（`d003`）：Chromium 底层报 `violates directive: img-src 'self' data: blob:`；`about:srcdoc` 强制继承宿主 policy container，且 Electron 全 session 强制重写 CSP，客户端直连外链图片必然被阻断；
    2. 方案审阅结论：经 Claude Code (`opus 5.5`, effort=`high`) 深度架构审阅，独立正文 URL 端点方案存在 XFO 阻断、Electron 强制覆盖及双重净化 mXSS 等严重技术债，正式废弃并 drop t067；
    3. 采纳业界最佳实践：立项建立服务端安全图片代理（Image Proxy），主站、桌面端与正文沙箱统一永久锁定 `img-src 'self' data:` 零外部出网安全基线；
    4. 严格收敛 SSRF 防护、无状态 HMAC Token 签发、位图魔数校验、实时撤销与挂载真实 `_SPA_CSP` 的 Playwright 自动化验证。

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
