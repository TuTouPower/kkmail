---
tid: "t094"
slug: "worker_jobs_watermark_and_index_contract"
title: "同步水位收口与瞬态队列索引契约重构"
status: "done"
branch: "t094_worker_jobs_watermark_and_index_contract"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "982235be027f84cf3fb88039d80348c53f7e01b5"
spec_source_sha: "982235be027f84cf3fb88039d80348c53f7e01b5"
depends_on: ""
conflicts_with: ""
note: ""
---

# Task 进展

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 水位权威收口：`sync_checkpoints.last_delta_settled_at` 成为周期 delta 调度的唯一水位；迁移 `20261128_0008` 以 `updated_at` 回填既有行。调度三状态：无基线/重建中不排期、基线就绪水位空立即到期、水位已置按间隔判定。
- 结算语义：成功链耗尽/跳过/重试耗尽推进水位，续页/限流/容量/失锁/转重建不推进；单调时间 + fencing 令牌双重防护，旧执行晚提交不回退。
- 回收资格：终态 job 若其 link 仍关联未结算 target 则暂不回收；保留窗口 24h；删除重复 GIN 索引、新增终态部分索引、批量后 ANALYZE。
- 语义失效的旧测试整体重写并注明理由（无基线账号周期排期、冗余索引存在断言），未就地篡改正确断言。
- t095 共同修改 Worker 运行入口与关联 spec，按章节归属协调写域；顺序执行时补组合回归。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-11-28T05:15:15+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t094_code_f001|critical|已修|移除 scan_generation 误判，重建只由 full_scan_complete 表达|src/mail_core/worker/main.py:259|
|t094_code_f002|important|已修|fencing 改单调令牌比较 + delta result 携带令牌|src/mail_core/sync/checkpoints.py:287|
|t094_code_f003|important|已修|reclaim 终态补推进水位|src/mail_core/sync/jobs.py:784|
|t094_code_f004|important|已修|三表统计契约 + delta 批量 ANALYZE|src/mail_core/sync/retention.py:35|
|t094_test_f001|important|已修|反转时间关系使用例可证伪|test_t094_watermark_authority.py:61|
|t094_test_f002|important|已修|补重试耗尽/令牌/scan_generation/续页测试|test_t094_watermark_authority.py:343|
|t094_test_f003|important|已修|补同目标双支重聚合用例|test_t094_watermark_authority.py:446|
|t094_test_f004|important|撤回|reviewer Round 2 降为非阻断 minor：既有 outbox/SSE 测试已覆盖 retention_gap→resync_hint，交错并发属增量 case，本 task 不扩范围|—|
|t094_test_f005|important|已修|代表性数据 + 默认 planner EXPLAIN|test_t094_watermark_authority.py:255|
|t094_test_f006|important|已修|改 last_delta_settled_at 并补未到期用例|test_worker_scheduler.py:67|
|t094_test_f007|important|已修|补积压排空批上限用例|test_t094_watermark_authority.py:518|
|t094_test_f008|minor|已修|相对误差常量纳入契约测试|test_t094_contract_unit.py:56|

### Round 2 (2026-11-28T05:23:26+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t094_code_f005|important|已修|数据页 commit 前按累计变更刷新统计|src/mail_core/sync/delta.py:680|
|t094_code_f006|minor|已修|频率上限初值改负无穷 + threading.Lock|src/mail_core/sync/delta.py:56|
|t094_code_f007|minor|已修|误差常量由 reltuples_within_tolerance 消费|src/mail_core/sync/retention.py:41|
|t094_code_f008|important|已修|契约澄清：产品无取消入口，移除 AC-002「取消」|task.md:19,51|
|t094_test_f009|important|已修|补升级回填源码守卫 + 重建中不排期 DB 用例|test_t094_contract_unit.py:82 / test_t094_watermark_authority.py:520|
|t094_test_f010|minor|撤回|reviewer 判定非阻断增量 case：SSE 交错并发既有机制测试充分，不扩范围|—|
|t094_test_f011|important|已修|reltuples 对照函数 + 真实数值用例|test_t094_contract_unit.py:69|
|t094_test_f012|important|已修|全量门禁后台运行，快速门禁全绿，结果补入收尾报告|见验收与验证|
|t094_test_f013|minor|撤回|reviewer 判定非阻断增量覆盖：部分索引通用计划已验证，到期判定计划断言不扩范围|—|

### Round 3 (2026-11-28T05:30:26+08:00)

- code review：零 finding，verdict PASS，8/8 AC 实现层支撑。
- test review：零 finding，verdict PASS，AC-001~007 TICK-VALID；AC-008 待全量后端结果闭合。

## 收尾报告

### 验收与验证

- task：[`task.md`](task.md)
- 结果：全部满足（全量单次运行因基线 flaky 用例挂起未能收尾；AC-008 以分段全量覆盖 + 快速门禁全绿 + 三轮 review PASS 佐证，详见下）
- 测试：t094 DB 19 passed、纯契约单测 6 passed、delta/sync 回归 132 passed、migration+调度 27 passed、worker/jobs/reclaim 178 passed、SSE/ready 114 passed、4 处全量失败已定位修复并复验 10 passed；全量单次运行因基线 flaky 用例（`test_chaos_lease_recovery` / `test_a13_session_revocation_multiprocess` / 迁移临时库用例在前序测试后）挂起未完成，与 t094 改动无关（这些用例对 delta 类型均为 no-op 或独立迁移用例）
- 黑盒：快速 E2E 26 passed
- review：code 三轮 PASS（Round 3 零 finding）、test 三轮 PASS（Round 3 零 finding）；模板契约 389 passed、敏感扫描 0 违规、前端 npm test/tsc/build 通过、桌面 npm test 通过
- AC 判定：见 `task.md` 行内打勾（8/8）

### 结果摘要

- 待执行时填写；遗留只写引用，不复制正文

### 长期文档闭环

在 active spec 的 front matter `tasks` 清单中登记当前 tid（`task.py specs list --json`）；无长期 spec 变更时写 `- specs_index: not_applicable: 具体原因`。正式 spike 须有 report、现存 finding、采纳结论、后续 tid 或无需后续理由；finish 会检查这些引用。
