---
tid: "t013"
slug: "test_pg_runtime"
title: "建立可复用 PostgreSQL 测试容器与每轮独立测试库"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: "t012,t014,t015,t016,t017,t018,t019,t020,t021,t022,t023"
note: "本会话批准测试增强；本地复用专用 PG 容器、每轮独立测试库；仅创建 backlog"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

创建依据：本会话测试评估与用户确认；2026-10-22 核对 run-mail-core-tests.sh、tests/mail_core/conftest.py 和 docker-compose.mail-core.yml。未启动容器或连接业务 DB。

### 2026-10-22 主分支执行

- 用户明确要求不用 task 工具链，直接在 main 按 t013–t023 顺序执行，保留逐项实现、验证、review 与提交思路。不启动 worktree、不写 attempt；front matter 保留原值，不作为本次实施完成证据。
- 已新增专用测试 Compose 与运行入口，建立容器/PG cluster identity、独立运行记录和数据库 comment 联合保护；直接 pytest 在收集前和 fixture 删除前验证。
- 包装入口不再每轮安装依赖；完整运行经生产 Alembic 创建 schema，结束、失败和可捕获中断走本轮清理，保留报告和所有权记录。
- 已执行保护测试与显式快速套件，PG 用例未执行。尚未启动测试容器或连接业务数据库。
- 用户已提供专用随机密码，保存至忽略文件 `.env.test`（0600），未复用业务密码。专用 PG 已启动，重复 start 保持容器 ID 与服务进程。
- 安全测试：17 passed；显式快速套件（已配置密码）241 passed / 103 skipped，PG live probes 确认不执行。完整套件 337 passed / 2 failed / 2 skipped，约 130 秒；失败为 LISTEN 消费前序残留、旧 SSE dispatch 测试未设置真实 subscriber。保留原始失败证据，完整连续两轮 AC 尚未通过，交由紧随其后的 t014 在获准测试隔离范围收口。
- 真实验证：两个独立仓库进程分配不同数据库与产物目录；取消首轮后第二轮哨兵保持。断言失败、真实 Alembic 迁移失败、SIGTERM 与分配阶段 OSError/KeyboardInterrupt 均验证清理；运行后无残留带标记数据库或 owner role。PG skip 回归证明失败报告为 exit 1，不产生 pytest INTERNALERROR。
- 独立代码 review：三项 important 已修复，末次复审未发现重要问题；见 `review_code.md`，未将完整 task 验收标为 PASS。
- 本轮先交付 runtime 实现；t013 全套验收仍待 t014 后复验，不伪写全部完成。t014–t023 尚未实施。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

尚未开始 review，无 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：尚未实施
- 测试：待执行时填写
- 黑盒：待执行时填写
- review：待执行时填写
- AC 证据：见 `handoff.json`

### 结果摘要

- 待执行时填写；遗留只写引用，不复制正文
