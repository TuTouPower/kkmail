---
tid: "t026"
slug: "mime_archive_decode_failure"
title: "邮件 MIME 解析失败在前端明确报错"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "来源 p020；用户确认不处理历史乱码；正文/报头/附件名解析失败持久记录并在前端报错；保留原文，无产品契约阻塞"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

来源 p020。2026-10-23 已核实 MIME 解析缺口及 parse_error 在前端转换丢失。用户澄清历史乱码已手动处理，无需历史乱码修复；任何本 task 涉及的 MIME 解析错误必须直接在前端报错。

范围收敛为正文/报头/附件名解析失败持久记录与阅读器明确提示。正常缺失字段提取不扩改，沿用原文归档与解析结果分离模型。原两项产品契约阻塞已消除；原 AC-001/AC-002 撤销且不复用，新前端行为编号 AC-006/AC-007。当前仅维护 backlog，不 start、不改生产代码。

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
