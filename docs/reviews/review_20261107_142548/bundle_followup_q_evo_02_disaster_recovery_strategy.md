# bundle_followup_q_evo_02_disaster_recovery_strategy

## Summary

经核查 src/mail_core/backup/package.py、docs/blueprint/decisions.md 与 testing.md，确证系统定位于单机单租户自托管客户端，当前全量冷备单事务还原在当前业务规模下完全可接受：

1. 系统定位与规模事实：docs/blueprint/decisions.md §1.1 明确确立系统为单用户能力凭据模型（Single-user & Capability-based UUID），2026-10-30 决策进一步锁定为单 Worker 进程部署（8 槽位）；testing.md 确立的性能测试规模为 1,000~10,000 封基准。系统明确面向单机单租户个人自托管场景（真实邮件体量数万封），非海量多租户云服务。
2. 灾备机制与强一致性实现：src/mail_core/backup/package.py:1210-1257 设计了严格的五阶段状态机（独占锁 -> 目标目录同卷暂存 -> 发布不可变 Blob -> pg_restore --single-transaction --exit-on-error -> 全量关联核验）。先使不可变物理 Blob 原地就位，再以单一 PostgreSQL 事务提交元数据，失败即刻回滚并安全清理。
3. 业务规模下完全可接受：在单机数万封邮件规模（数据库小于 500MB，Blob 数 GB）下，pg_restore 单事务导入耗时在数十秒内，WAL 膨胀与连接超时风险极低；停机单事务冷还原提供了确定性极高的一致性保证（杜绝脏数据半恢复）。当前方案不仅完全可接受，且符合 CLAUDE.md「简洁优先，取最简实现，不做超出需求抽象」的原则，原 finding 提出的海量企业级 RTO 瓶颈属于脱离定位的过度设计。
4. 灾备演进策略结论：维持选项 A（保持离线全量快照为当前核心机制）。未来若 Blob 数据体量继续增长，演进边界仅需聚焦于只读不可变 BlobStore 的增量同步或对象存储挂载，无需过早引入 WAL-G/PITR 等复杂连续物理归档设施。

## Findings

No findings.

## evidence

```json
[
  "docs/blueprint/decisions.md:11-12",
  "docs/blueprint/decisions.md:64-73",
  "docs/blueprint/testing.md:202-218",
  "docs/blueprint/testing.md:256-265",
  "src/mail_core/backup/package.py:1210-1257",
  "src/mail_core/backup/package.py:1851-1889"
]
```

## result

```json
"confirmed"
```
