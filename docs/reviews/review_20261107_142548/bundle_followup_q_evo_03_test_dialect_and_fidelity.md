# bundle_followup_q_evo_03_test_dialect_and_fidelity

## Summary

经核查 src/mail_core/realtime/publication.py:38-42、tests/mail_core/sqlite_schema.py 及全仓测试实现，核实了 SQLite 兼容分支对架构纯洁性与测试保真度的负面影响，并确立了明确的消除路径：

1. 生产代码妥协影响：src/mail_core/realtime/publication.py:33-43 显式编写了 elif dialect == 'sqlite': ... sqlite_insert ... on_conflict_do_nothing()，并在 L42 自注 # pragma: no cover - production is PostgreSQL, tests SQLite。此特判属于生产代码向测试基础设施妥协的架构反模式，直接违背 AGENTS.md「拒绝妥协」铁律。
2. 测试失真与虚假断言影响：SQLite 无法模拟 PostgreSQL 的 JSONB 字段特性、tsvector 全文检索、行级排他锁（FOR UPDATE SKIP LOCKED）、咨询锁以及 LISTEN/NOTIFY 机制。测试层通过 tests/mail_core/sqlite_schema.py 粗暴进行字符串替换（将 JSONB/::jsonb 抹为 JSON）来强行在内存 SQLite 中运行单测。这导致 20 多个测试脱离真实数据库语义；更诱发了如 tests/mail_core/test_t062_outbox_and_job_notify_wake.py:359-367 声称测非 PG 方言实际仅建 dummy 表并 INSERT 1 的完全脱靶断言，产生虚假安全网。
3. 清晰消除路径：
    a. 生产端：直接剔除 publication.py 中的 sqlite 分支，仅保留标准的 PostgreSQL 方言处理；
    b. 测试端：项目在 docs/blueprint/testing.md 与 scripts/run-mail-core-tests.sh 中已有成熟隔离的测试容器与独立测试库分配机制（kkmail_test\_<UUID>），将依赖 sqlite:// 的 20 余个测试文件全面接入真实 PostgreSQL fixture；
    c. 清理垫片：彻底删除 tests/mail_core/sqlite_schema.py，重写或删除 test_t062 中的虚假断言。
4. 结论：确认为 confirmed，坚决执行选项 A（彻底移除 SQLite 兼容分支，测试统一收敛至真实 PostgreSQL）。

## Findings

No findings.

## evidence

```json
[
  "src/mail_core/realtime/publication.py:33-44",
  "tests/mail_core/sqlite_schema.py:1-20",
  "tests/mail_core/test_t062_outbox_and_job_notify_wake.py:359-367",
  "tests/mail_core/test_a352_publication_state_race.py:22-38",
  "docs/blueprint/testing.md:97-101"
]
```

## result

```json
"confirmed"
```
