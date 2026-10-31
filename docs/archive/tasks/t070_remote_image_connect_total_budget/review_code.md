# Task review t070（reviewer_focus: 代码）

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

1. 规格合规：
    - `_connect_with_fallback` 的 `timeout` 参数语义明确为总预算，`deadline = time.monotonic() + timeout`（AC-001）。
    - 每次尝试 `remaining = deadline - now`，`remaining <= 0` 直接停止并标记超时；单次超时 `min(CONNECT_TIMEOUT_SECONDS, remaining)`（AC-002）。
    - 成功短路、IPv4 优先、非超时全失败归 502 的行为未变；`fetch_safe_remote_image` 传入 `TOTAL_CONNECT_TIMEOUT_SECONDS`（15s）（AC-003）。
2. 代码质量：
    - 改动集中在一个函数，无重复逻辑；`time` 导入与常量命名清晰。
    - 边界处理正确：预算恰好耗尽时 `remaining == 0` 归入超时而非继续尝试。
    - 文件体积不变（`remote_image_proxy.py` 约 570 行，既有大文件小幅改动）。
3. 安全：
    - 仅调整尝试调度，未改变 IP 校验、直连校验 IP、TLS SNI 与重定向策略。

### AC 复验方式

- AC-001：`re_verified` — `test_connect_shares_total_budget_across_attempts` 用假时钟证明三次 5s 后预算耗尽、第 4 个 IP 不再尝试；API 超时映射 504 既有用例保留。
- AC-002：`re_verified` — `test_connect_last_attempt_uses_remaining_budget` 断言最后一次超时为剩余 3s；首轮预算充足时仍为 5s（同一断言序列）。
- AC-003：`re_verified` — `test_connect_success_short_circuits_budget`、`test_connect_falls_back_across_safe_ips_ipv4_first`、`test_connect_all_ips_unreachable_maps_to_fetch_error` 全部保留通过；代理 PG 集成 33 passed。

coverage = 3 / 3 (100%)

verdict: PASS
