---
tid: "t019"
slug: "backup_restore_drill"
title: "建立真实加密备份与跨库恢复演练"
status: "done"
branch: "main"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "4ea0a6f17fb5dce8de4c15d869eaf879705ddcbb"
depends_on: "t014"
conflicts_with: ""
note: "本会话批准测试增强；本地复用专用 PG 容器、每轮独立测试库；已于 2026-10-22 在 main 直接执行并完成（未用 task 工具链/worktree），实现 commit 1312431b"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

2026-10-22 核实 test_backup_verify_drill.py 和 mail-core-backup-restore-drill.sh 均无真实 pg_restore；沿用已有加密与包格式。

### 2026-10-22 主分支执行

- 用户明确要求直接在 main 分支按顺序执行 t013–t023，每完成一个 task 独立 commit。
- 生产恢复能力补齐：在 `src/mail_core/backup/package.py` 实现 `restore_backup_package` 与 `RestoreResult`，支持校验前置、解包、解密、`pg_restore` 真实数据库恢复以及 Blob 目录还原。
- 安全防护与目标检查：
    - AC-004：严格拒绝源库与目标库相同，防止破坏性覆盖；检查目标 Blob 目录拒绝路径穿越与越界符号链接；
    - AC-003：错误密钥拒绝、文件篡改校验失败、缺少引用 Blob 抛出明确异常；
    - AC-005：拒绝将 SQL stub 备份作为可恢复备份。
- 建立客户端代理：在 `scripts/test_pg_client/` 提供基于测试 PG 容器的真实 `pg_dump` 与 `pg_restore` 代理，映射宿主机与容器端口；在 `scripts/test_pg_runtime.py` 的测试环境中注入 PATH。
- 新增 `tests/mail_core/test_backup_restore_drill_live.py`：
    - 在源库注入账号、邮件、正文、附件并写入真实加密 Blob；
    - 生成真实加密备份包并完成校验；
    - 动态分配全新目标数据库 `kkmail_drill_target_*` 并执行恢复；
    - 在目标库中完整断言账号、邮件主题/正文、附件文件，并使用密钥解密读取 Blob 比对原始字节；
    - 执行失败边界与篡改防护测试。
- 门禁通过：2 项测试全通过 (5.73s)；`scripts/mail-core-backup-restore-drill.sh` 顺利完成。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

- 已修：归档解包结构修正，对齐 `postgres.dump` 与 `blobs.tar`；
- 已修：测试客户端代理映射端口 `:15433` 到 `:5432`；
- 双人审查（code + test）结论均 PASS。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：真实加密备份与跨库恢复演练闭环，全部行为 AC 均满足。
- 测试：`scripts/run-mail-core-tests.sh run -k test_backup_restore_drill_live` 2 passed。
- 黑盒：源库全实体加密备份 -> 全新独立数据库与 Blob 还原 -> 目标库业务实体与加密 Blob 字节核验。
- review：`review_code.md` PASS，`review_test.md` PASS。
- AC 证据：`test_backup_restore_drill_live.py` 与 `mail-core-backup-restore-drill.sh` 终端实测输出。

### 结果摘要

在生产备份模块补齐了真正的恢复逻辑 `restore_backup_package` 与安全防覆盖守卫；建立了基于真实 PostgreSQL 容器与原生 `pg_dump`/`pg_restore` 的跨库恢复演练测试，证明了数据库结构、业务数据及加密 Blob 可以完整、无损地还原到全新实例中。

## 状态勘误（2026-10-27，A52）

- 本节为事后补记，不覆写上文历史：front matter 创建期原值 branch/diff_anchor 为空、note 尾句为「仅创建 backlog」，与 done 状态及正文实施记录矛盾，现已按实际执行方式勘误补记。
- 实际执行方式：2026-10-22 按用户要求直接在 main 分支执行（不使用 task.py、worktree 或 attempt），与正文「2026-10-22 主分支执行」节一致。
- commit 锚点：实现提交 `1312431b58ada455a994c0842e52947a28cc0422`；diff_anchor 补记为该实现提交的父提交 `4ea0a6f17fb5dce8de4c15d869eaf879705ddcbb`；本批归档提交 `161a6e10`。
- `docs/archive/tasks_index.json` 已在本批（t013–t023）补记全部完成后按勘误后的 front matter 重新生成。
