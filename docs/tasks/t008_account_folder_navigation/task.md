---
tid: "t008"
slug: "account_folder_navigation"
title: "支持真实账号文件夹与收藏分类导航"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "来源 p013；复用 folder-stats 与角色检索，补齐精确文件夹范围"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

创建依据：p013（2026-10-22 核实：Sidebar 只有三类收藏；mailStore 及 listTitle 无 folder 状态；MessageList 只把 sent 转为 sent，其余使用 inbox。mail.py 与 queries.py 已支持任意 folder_role，folder-stats 含 folder_id/name/remote_id/role，DB 已有 parent_remote_id 但响应未暴露。Stub LIST 四个 SPECIAL-USE 标志均复现 other；已有测试只覆盖 Sent 标志、中文已发送和默认/sent 查询。t003 已完成但未交付本范围，无等价 effective task。）

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
