---
pid: "p094"
slug: "label_backfill_lease_ttl_too_short"
status: "closed"
resolution: "resolved"
reason: "回填维护租约 TTL 提升为 30 分钟，新增分钟级断言；unit 1694 passed"
fix_ref: "main"
---
# p094 回填租约 TTL 120s 对 Gmail 慢分页过短

- 现象：生产回填中 `fengandelliot@gmail.com` 的 5 个目录全部因 `lease heartbeat rejected: lease expired` 被跳过，账号仍标记 `completed`，但实际未完整扫描。
- 影响：完成标记不可信；历史 Important 成员仍可能缺失。其它账号未出现该问题。
- 根因：`mail_core.sync.label_backfill.LEASE_TTL` 沿用同步任务的 120s，但维护型回填单页 FETCH 可能超过 120s，第一页尚未返回租约已过期；LEASE_TTL 应覆盖维护作业的慢分页。
- 测试缺口：现有 PG 用例的分页瞬时返回，未覆盖长页导致租约过期；补断言常量为分钟级并验证心跳仍有效即可。
- 线索：生产回填输出（账号 `09242245...` 的 5 条 `lease heartbeat rejected`）。
- 处理：main；resolution=resolved；reason=回填维护租约 TTL 提升为 30 分钟，新增分钟级断言；unit 1694 passed
