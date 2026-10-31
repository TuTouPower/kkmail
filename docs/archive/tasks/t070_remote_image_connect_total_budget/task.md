---
tid: "t070"
slug: "remote_image_connect_total_budget"
title: "远程图片代理多 IP 回退总超时预算"
status: "done"
branch: "t070_remote_image_connect_total_budget"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "307b0dcc0a8c092a4bd9c3a82d9455390ede107c"
depends_on: ""
conflicts_with: ""
note: "t069 AC-006 实现补齐：多 IP 回退整次连接共享 15s 总预算，避免 N×5s 最坏等待"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 实施决策：
    1. 新增 `TOTAL_CONNECT_TIMEOUT_SECONDS = 15.0`；`_connect_with_fallback` 的 `timeout` 参数语义改为整次连接总预算，内部以 `time.monotonic()` 计算 deadline；
    2. 每个 IP 尝试超时取 `min(CONNECT_TIMEOUT_SECONDS, remaining)`；`remaining <= 0` 时不再发起连接并归入超时（504）；
    3. 成功即返回、IPv4 优先、全部非超时失败归 502、只连已校验 IP、TLS SNI 保持原域名的既有行为不变；
    4. 新增三例假时钟单测：预算耗尽停止（5+5+5=15，不再试第 4 个 IP）、最后一次使用剩余预算（5/5/5/3）、成功短路。
- 验证：后端单测 31 passed；代理 PG 集成 33 passed；前端 mailBody 25 passed；E2E 21 passed；契约 189 passed。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-31T19:20:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：后端单测 31 passed（含新增预算三例）；代理 PG 集成 33 passed；前端 mailBody 25 passed；契约 189 passed
- 黑盒：`npm --prefix src/frontend run test:e2e` 21 passed
- review：Round 1 code PASS + test PASS 零 finding
- AC 证据：见 `handoff.json`

### 结果摘要

- 多 IP 回退改为整次连接共享 15s 总预算，单 IP 尝试上限 5s，预算耗尽立即停止并返回 504；避免 N×5s 最坏等待。
