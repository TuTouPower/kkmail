# Task review t049（reviewer_focus: 代码）

- task：`t049_sync_retry_double_enqueue`
- spec：`docs/tasks/t049_sync_retry_double_enqueue/spec.md`
- diff_anchor：`d3fd350`。
- target：`git -C /Users/karson/kar/code/kkmail diff d3fd350`。
- 审查方式：独立审查 d3fd350 后的 t049 变更；未修改生产代码。
- 流程限制：用户授权直接 main，task front matter 的 `diff_anchor` 为空；现工具只能在 start worktree 时赋值，因此无法渲染正式 prompt。本报告按 code/shared prompt 规则人工审查；不伪造 active/done 或 worktree identity，不声称通过 task-work 状态门禁。
- round：1
- reviewed_at：2026-10-24T03:26:52+08:00

## Findings

### t049_code_f001 - 已有后继任务时 Worker 仍可能再次入队

- 严重度：important
- 锚点：AC-002；结果标记为 `followup_scheduled` 后仍可能产生第二条 pending 后继任务。
- 位置：`src/mail_core/worker/handlers.py:61`
- 问题：该标记让原任务进入完成分支，但分支仍按原 payload 的 `_followup_needed` / `_followup_run_after` 执行 Worker followup enqueue（`src/mail_core/worker/handlers.py:71-83`）。若 claimed job 的同 dedupe key 请求在执行期间设置该 payload 标记，内部同步路径已提交一条后继任务，Worker 随后仍创建另一条，AC-002 的单后继保证不成立。
- 建议：`followup_scheduled` 为真时完成原任务并跳过 Worker followup enqueue；增加 claimed payload 已有 `_followup_needed` 的回归测试，断言最终仅有同步层提交的一条后继任务。

## 结论

- 本轮新发现：1 条 important；需要修复并重审。
- 未进表的提示：无。
- 总体判断：显式标记修复了普通错误双排队，但与 Worker 的唤醒标记合并时仍可重复入队。
- 系统性 follow-up：当前 task `t049`。

verdict: FAIL

## Round 2 (2026-10-24T03:28:24+08:00)

reviewed_scope: aea9011519a4c39a

- target：`git -C /Users/karson/kar/code/kkmail diff d3fd350 -- src/mail_core/sync/delta.py src/mail_core/sync/engine.py src/mail_core/worker/handlers.py tests/mail_core/test_sync_retry_queue.py docs/blueprint/conventions.md`。

### 前轮 finding 复核

- `t049_code_f001`：已消除。`followup_scheduled` 为真时，Worker 不读取 `_followup_needed` / `_followup_run_after` 来创建第二条任务，也不使用结果 `next_run_after` 追加排队；仍会完成原 claimed job。新 PG 用例设置原 job 的 `_followup_needed` 与 dedupe key，并断言只剩一条 pending 后继。

### Findings

无新 finding。

### 结论

- 前轮 important finding 已修复，回归测试覆盖触发条件。
- 本轮新发现：0 条。
- 未进表的提示：无。
- 总体判断：Worker 只完成原任务并保留同步层已提交后继；普通成功续跑和未标记失败分支保持原逻辑。
- 系统性 follow-up：无。

verdict: PASS

## Round 3 (2026-10-24T03:38:17+08:00)

reviewed_scope: bf3efa390aac9033

- target：`git -C /Users/karson/kar/code/kkmail diff d3fd350`。
- 复核范围：最终 spec、Worker 与同步入口实现、队列回归测试及 blueprint；生产代码相对 Round 2 无变化。

### 前轮 finding 复核

- `t049_code_f001`：Round 2 已修复；本轮重新对照最终 diff，Worker 在 `followup_scheduled` 时完成原 job 并跳过通用 followup 入队逻辑，未回归。

### Final AC 复核

- AC-001、AC-002、AC-003 均已在最终 spec 勾选；实现和 PostgreSQL 回归覆盖与勾选结果一致。
- 本轮新发现：0 条。
- 总体判断：最终 spec 与代码、测试证据一致，未发现新的阻断或范围偏离。
- 流程限制：direct-main 的正式 prompt 渲染和 task-work 状态门禁限制见本报告开头；不将其宣称为通过。

verdict: PASS

## Round 4 (2026-10-24T03:47:38+08:00)

reviewed_scope: 1eb3b40c21ee29c1

- target：`git -C /Users/karson/kar/code/kkmail diff cdfafc7`。
- 范围隔离：以修复前 main HEAD `cdfafc7` 为基线；该提交包含独立 t050 登记，本轮仅审查其后的 t049 最终交付，不纳入 t050 task 登记。
- 复核内容：最终 spec 的 AC 勾选、同步层标记、Worker 处理、队列回归测试与 blueprint；t049 生产代码与 Round 3 相同。

### 前轮 finding 复核

- `t049_code_f001`：已修复且未回归。`followup_scheduled` 分支会完成原 job，并跳过通用 followup enqueue。

### Findings

无新 finding。

### 结论

- t049 最终 spec 与实现、测试覆盖一致；AC-001..003 均有对应实现和验证证据。
- 已隔离 t050 独立 task 登记；未发现 t049 新问题。
- 总体判断：PASS。

verdict: PASS
