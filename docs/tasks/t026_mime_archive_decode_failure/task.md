---
tid: "t026"
slug: "mime_archive_decode_failure"
title: "修复 MIME 归档报头与附件名解码并显式记录损坏数据失败"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "来源 p020；裸 GBK MIME 报头与附件名均复现乱码；回填保留边界及解析失败状态待确认，禁止 start"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

来源 p020。2026-10-23 已用现有复现脚本确认报头与附件名解码缺口。用户范围问题已发出：是否保留缺失元数据提取，以及不可恢复解析失败是否允许保留原文归档完成状态；未收到答复，已标记 UNVERIFIED-BLOCKING，不能 start。当前 AC 明示推荐方案，并非产品批准。

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
