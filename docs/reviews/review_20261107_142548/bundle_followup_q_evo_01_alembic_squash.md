# bundle_followup_q_evo_01_alembic_squash

## Summary

经核对 AGENTS.md、docs/blueprint/decisions.md、docs/blueprint/testing.md 与 Alembic 迁移源码，确证当前无外部公共分发，架构上完全允许并强烈建议直接 Squash 迁移链：

1. 外部生产分发事实：核实确认系统当前无任何外部商业分发、公共镜像发布或多版本兼容需求。项目定位于单用户自托管客户端；桌面端打包维持未签名且未上架任何应用商店（decisions.md §1.5）；远程 CI/CD 发布流水线已彻底移除（decisions.md 2026-10-22 变更注记），仅由开发者在本地及私有自托管环境运行，不存在不可控的外部存量数据库升级负担。
2. 架构规范事实：AGENTS.md 核心架构铁律明确规定「零兼容性负担：直接执行破坏性变更，完全不需要考虑前后兼容」与「架构至上：始终选择最优雅、彻底、纯粹的顶层设计与架构方案，完全忽略开发难度与改动工作量」。保留 30 个密集迭代补丁属于典型的兼容性历史包袱。
3. 迁移链现状事实：0001~0030 仅在 11 天内生成，包含大量探索期中间态。例如 20261027_0027 对大表执行同步 STORED 计算列重写和非 CONCURRENTLY 的 GIN 索引持有排他锁，0028 立即全表 UPDATE 修补数据，多个版本 downgrade 声明为 pass，迁移链质量与长期维护性堪忧。
4. Squash 消除路径与影响：完全允许将 0001~0030 压缩合并为当前最新权威单一基线（如 0001_unified_baseline）。前置影响仅为两项工程适配：需同步重构 tests/mail_core/test_migration_validation.py 中依赖历史 revision（0002/0011/0014）的旧窗口测试，并为既有自托管生产库执行一次 alembic stamp 升级。

## Findings

No findings.

## evidence

```json
[
  "AGENTS.md:12-16",
  "docs/blueprint/decisions.md:25-27",
  "docs/blueprint/decisions.md:88-96",
  "docs/blueprint/testing.md:186-201",
  "src/mail_core/db/alembic/versions/20261027_0027_search_recipient_and_account_recipients.py:28-56",
  "src/mail_core/db/alembic/versions/20261027_0028_rebuild_recipient_search_text.py:1-45",
  "tests/mail_core/test_migration_validation.py:59-78"
]
```

## result

```json
"confirmed"
```
