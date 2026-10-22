---
tid: "t018"
slug: "migration_validation"
title: "验证空库与旧数据升级及数据库结构一致性"
status: "done"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: "t013"
conflicts_with: ""
note: "本会话批准测试增强；本地复用专用 PG 容器、每轮独立测试库；仅创建 backlog"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

2026-10-22 核实生产迁移链共 15 个文件，test_schema_pg 仅 REQUIRED 表与基础插入；创建阶段不执行数据库迁移。

### 2026-10-22 主分支执行

- 用户明确要求直接在 main 分支按顺序执行 t013–t023，每完成一个 task 独立 commit。
- 新增 `tests/mail_core/test_migration_validation.py`：
    - AC-001：断言 15 个迁移版本线性单 head，无多分支与孤立 revision；
    - AC-002：降级到三个实际历史窗口（`f5f312751c77` unified schema、`20261021_0011` 认证入库前、`20261022_0014` 最近版本前一版），使用当时合法 SQL 写入邮件、附件、凭证与重试任务，升级至当前 head 后逐项断言邮件正文、附件 backfilled `part_id`、登录哈希与 session_epoch 完整保留；
    - AC-003：真实 PostgreSQL 关系约束生效，插入重复 `(account_id, remote_id)` 或非法外键抛出 IntegrityError；MessageBlob 受 links 引用 RESTRICT 阻止删除；验证 FTS 全文搜索表与 keyset 排序索引；
    - AC-004：利用 `compare_metadata` 校验 SQLAlchemy ORM 与真实 PG catalog 0 结构差异；显式绑定 TSVECTOR 计算列与 GIN 专属索引；负向测试在内存模型增加未迁移列时准确检出 drift；
    - AC-005：对当前 head (`20261022_0015`) 执行 `downgrade -1` 与重新 `upgrade head` 对称循环，验证可逆性与 DDL 正确性。
- 修复 URL 转义：在动态加载 Alembic ConfigParser 时对密码中的 `%` 双写为 `%%`，防止 BasicInterpolation 语法错误。
- 门禁通过：5 项测试全通过 (6.24s)。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

- 已修：历史 SQL 字段对齐（`message_locations.id`, `remote_operations.entity_key`, `auth_credentials.login_password_hash`）；
- 已修：ORM drift 比较逻辑中对 PostgreSQL generated tsvector 及 GIN 索引进行显式 catalog 校验；
- 双人审查（code + test）结论均 PASS。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：数据库迁移验证与结构完整性门禁建立完成，全行为 AC 均满足。
- 测试：`scripts/run-mail-core-tests.sh run -k test_migration_validation` 5 passed。
- 黑盒：多版本数据跨版本平滑升级保留、约束阻断非法操作、降级再升级结构恢复验证。
- review：`review_code.md` PASS，`review_test.md` PASS。
- AC 证据：`test_migration_validation.py` 实测输出。

### 结果摘要

建立了完整的数据库迁移与结构一致性测试，涵盖单链单 head 校验、三版本历史数据跨版本升级无损保留、PostgreSQL 完整性约束与级联、ORM catalog drift 零差异检测以及可逆降级升级闭环。
