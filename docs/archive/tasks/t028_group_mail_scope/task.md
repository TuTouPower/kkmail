---
tid: "t028"
slug: "group_mail_scope"
title: "贯通分组邮件查询与批量已读范围"
status: "dropped"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: "t026"
note: "来源：侧栏设计聊天与 v3 demo；保留现有全部分类并贯通分组查询、搜索、统计和全部已读；空分组禁止退化为全账号；demo 不构成功能删减依据; dropped: 已合并至 t027：完整改造账号分组侧栏与邮件范围；原 AC-001–007 映射为 t027 AC-010–016，全部保留"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 创建依据：2026-10-23 核对设计聊天、v3 本地原型与 main@26a8eee。仅登记 backlog，未 start、未实施。

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
