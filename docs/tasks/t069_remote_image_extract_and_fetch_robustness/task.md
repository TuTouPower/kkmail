---
tid: "t069"
slug: "remote_image_extract_and_fetch_robustness"
title: "远程图片提取与代理容错修复"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "来源 p069；修复无引号 src/实体/协议相对漏提取，统一服务端 HTML5 解析语义，区分 DNS/网络/上游/安全错误码，SVG 安全放行与多 IP 回退"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 创建期事实与量化（来源 `p069`）：
    1. L1 全库扫描 19897 封有正文 / 18389 封含 `<img>`：558 封提取为 0（全碎）、2519 封部分漏提取、2874 封 HTML 实体不一致、2 封仅协议相对；
    2. L2 真实试拉 800 URL：556 成功；DNS 失效被误报 SSRF 拦截 22、上游 4xx/409 与超时混同 502、合法 SVG 被 415 拒 16；
    3. L3 生产 CSP + 生产代理端点 + 真实 Chromium：Google 原邮件两张图 `naturalWidth` 160/512，零 CSP 违规，确证代理链路完好、缺陷仅在提取。
- 待实施验证的修复面：F1 无引号、F2 实体、F3 协议相对、F4 错误分类、F5 多 IP 回退、F6 SVG 安全放行。

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
