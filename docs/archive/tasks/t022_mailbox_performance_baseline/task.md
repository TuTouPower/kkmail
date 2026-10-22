---
tid: "t022"
slug: "mailbox_performance_baseline"
title: "建立大邮箱查询同步与资源使用基准"
status: "done"
branch: ""
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: "t014"
conflicts_with: ""
note: "本会话批准测试增强；本地复用专用 PG 容器、每轮独立测试库；仅创建 backlog"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

来源为本会话用户批准测试增强；性能结论尚未测量，task 交付为可重放基线与测量工具，不虚构当前性能或阈值。

### 2026-10-22 主分支执行

- 用户明确要求直接在 main 分支按顺序执行 t013–t023，每完成一个 task 独立 commit。
- 新增可重放基准工具 `scripts/benchmark_mailbox.py`：
    - AC-001：基于固定 seed 确定性生成 1k/10k/100k 规模邮箱测试集，涵盖中文全文主题、多部分正文、附件、Blob 与全文搜索索引；
    - AC-002：对首页 keyset 查询、深分页 keyset 推进、中文/ASCII 搜索、未读统计和流式 Blob 读取执行至少 3 次预热和测量，计算 p50/p95 延迟、吞吐，保证分页无重复无漏项；
    - AC-003：同步采集进程峰值 RSS（MB）、数据库总容量、Message 表大小、Blob 磁盘空间、EXPLAIN 执行计划，以及平台/CPU/Python/Git Commit 等环境元数据；
    - AC-004：采用受控测试目录与临时测试库，流式读写不产生全内存驻留扭曲；
    - AC-005：提供 `compare_reports` 差异比对能力，展现延迟百分比波动、内存变化与存储变化，并在跨平台比较时告警。
- 新增自动化测试套件 `tests/mail_core/test_mailbox_performance_baseline.py`：
    - 验证基准指标齐全有效（p50/p95、QPS、RSS、DB 大小、Query Plan）；
    - 验证基准对比差异生成。
- 门禁通过：2 项自动化测试全通过 (6.56s)。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

- 已修：批量数据生成中 `Message` 先行 flush，消除级联外键约束冲突；
- 单人审查结论 PASS（见 `review_general.md`）。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：大邮箱查询同步与资源使用基准工具及自动化测试门禁建立完成，全行为 AC 均满足。
- 测试：`scripts/run-mail-core-tests.sh run -k test_mailbox_performance_baseline` 2 passed。
- 黑盒：生成 1000 封确定性邮箱数据 -> 首页与深翻页 keyset 查询 -> 全文检索 -> 文件夹统计 -> Blob 流式读取 -> 捕获 EXPLAIN 计划与资源用量 -> 生成并比对基准报告。
- review：`review_general.md` PASS。
- AC 证据：`test_mailbox_performance_baseline.py` 终端实测输出。

### 结果摘要

交付了确定性大邮箱基准与资源性能测量体系，覆盖 1k/10k/100k 确定性数据生成、首页与深分页 keyset 延迟分位数、中文 FTS 搜索、文件夹统计与 Blob 流式解密吞吐，并自动采集进程 RSS、数据库大小、EXPLAIN 计划与跨报告回归对比能力。
