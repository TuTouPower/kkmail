---
tid: "t034"
slug: "on_demand_body_sync_and_archive_priority"
title: "按需即时同步邮件正文与归档调度优化"
status: "done"
branch: "t034_on_demand_body_sync_and_archive_priority"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "ed3bfeecc579b99de892b9c364de03101efb9531"
depends_on: ""
conflicts_with: ""
note: "来源 p021；用户点击未同步邮件时按需置为最高优先级即时拉取正文，修复增量轮询导致的归档饥饿"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. **调度优先级治理与去重保护**：将定时增量空转轮询优先级降为 75（并增加 `dedupe_key=f"delta:{aid}:{fid}"` 防止短时间内重复入队堆积），批量正文归档续批优先级提升为 60（高于 75，彻底解除增量轮询对批量正文归档的饥饿压制）。
2. **按需即时正文归档链路**：在详情查询与新增端点 `POST /api/mail/messages/{id}/sync-body` 中，检测到未完成归档时将 `MessageArchiveState.priority` 提升为 0 并入队最高优先级的即时归档任务（priority=10）；同时支持就地单封归档尝试以即刻响应；若抓取失败或 MIME 损坏，同步持久化 `MessageBody.parse_error`。
3. **前端交互与平滑渲染**：在 `MessageReader` 中检测到未归档正文时，展示旋转动态加载提示并在后台即时同步完成后平滑渲染正文，失败时展示具体原因与重试按钮，并与合法空邮件明确隔离。
4. **测试与契约生成**：TDD 新增后端 `test_on_demand_body_sync.py` 与前端 `MessageReader.test.tsx` 单元测试，OpenAPI 导出与 schema 重新生成并通过校验。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T06:05:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：后端测试全量 397 passed（含 `test_on_demand_body_sync.py`）、前端 195 passed + tsc ok + build ok + lint ok、桌面端测试 ok
- 黑盒：Playwright UI 冒烟测试 8 passed、真实全栈端到端测试 3 passed
- review：双轴审阅均 PASS（`review_code.md` PASS, `review_test.md` PASS, scope: `86dfd16022521d64`）
- AC 证据：见 `handoff.json`

### 结果摘要

- 实现未归档邮件按需最高优先级（priority=10）即时正文拉取与落库；
- 治理 Worker 任务调度优先级倒挂与饥饿问题，解除增量轮询对后台批量归档的压制；
- 前端提供正在同步动态加载反馈、错误原因展示与重试交互，平滑自动渲染正文。
