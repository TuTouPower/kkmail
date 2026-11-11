# Task review t070（reviewer_focus: 测试）

- task：`t070_remote_image_connect_total_budget`
- spec：`docs/tasks/t070_remote_image_connect_total_budget/spec.md`
- diff_anchor：`307b0dcc0a8c092a4bd9c3a82d9455390ede107c`
- target：`git -C '$WORKTREE' diff 307b0dcc0a8c092a4bd9c3a82d9455390ede107c`
- round：1
- reviewed_at：2026-10-31T19:20:00+08:00
    reviewed_scope: 905ce131a10a0032

## Round 1 (2026-10-31T19:20:00+08:00)

### Findings

Round 1 零 finding。

### 维度核验

1. 测试可信：
    - 假时钟 `monkeypatch` 精确控制 `time.monotonic`，注入 connector 记录每次传入的超时值，断言的是生产函数真实调度行为，不是 mock 被测逻辑。
    - 三例分别覆盖：预算耗尽停止、最后一次使用剩余预算、成功短路。
2. 覆盖：
    - AC-001/002 由预算两例直接覆盖；AC-003 由成功短路、IPv4 顺序、全不可达分类三例与既有集成回归覆盖。
    - 既有代理集成（SSRF/大小/Token/撤销/错误分类）全部保留通过（33 passed）。
3. 危险模式扫描：
    - 无恒真断言、无删断言、无 skip、无类型忽略。
    - 假 connector 注入是生产函数既有测试注入点，不 mock 业务分支；断言为精确数值列表（`[5.0, 5.0, 5.0]`、`[5.0, 5.0, 5.0, 3.0]`），非弱化断言。
    - 未修改既有测试断言语义。

### AC 复验方式

- AC-001：`re_verified` — 重跑 `test_connect_shares_total_budget_across_attempts`，attempted 恰为三次 5s，第 4 个 IP 未尝试。
- AC-002：`re_verified` — 重跑 `test_connect_last_attempt_uses_remaining_budget`，最后超时为 3s。
- AC-003：`re_verified` — 重跑代理 PG 集成 33 passed 与 E2E 21 passed，既有行为无回归。

coverage = 3 / 3 (100%)

verdict: PASS
