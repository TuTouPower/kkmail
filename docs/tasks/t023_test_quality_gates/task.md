---
tid: "t023"
slug: "test_quality_gates"
title: "将完整测试分层接入本地门禁与 CI"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: "t017,t018,t019,t020,t021,t022"
conflicts_with: "t012,t013,t014,t015,t016,t017,t018,t019,t020,t021,t022"
note: "本会话批准测试增强；本地复用专用 PG 容器、每轮独立测试库；仅创建 backlog"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

2026-10-22 核实 .github/workflows 不存在，testing.md 日常 pytest 与 release.md 完整 DB 脚本不一致。CI 服务/仓库权限在实施时核对，创建不触发外部写操作。

### 2026-10-22 主分支执行

- 用户明确要求直接在 main 分支按顺序执行 t013–t023，每完成一个 task 独立 commit。
- 建立 GitHub Actions 工作流：
    - `.github/workflows/ci.yml`：PR/Push 核心门禁，包含 `template-contract`、`frontend-quality`、`desktop-quality` 和 `backend-and-integration` 四大并行 Job，以及 `ci-status` 强状态汇总结算；覆盖全套前端、桌面打包、Python 后端、真实 PostgreSQL/IMAP 与全栈 E2E；
    - `.github/workflows/scheduled.yml`：定时/手动演练，执行真实备份还原演练、历史数据迁移演练、Worker 多进程混沌恢复与大邮箱性能基准。
- 更新蓝图与文档：
    - `docs/blueprint/testing.md`：规范化 `test_cmd` 与 `blackbox_verify`，统合 8 大分层本地执行命令与 CI 映射矩阵；
    - `docs/blueprint/decisions.md`：记录 CI 分层门禁与只读发布边界决策。
- 本地全矩阵重放验证：所有分层命令在本地全部 100% 验证通过。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

- 已修：汇总 Job 采用 `if: always()` 防止上游失败被跳过导致假绿；
- 已修：工作流权限严格限定为 `contents: read`；
- 双人审查（code + test）结论均 PASS。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：完整测试分层与 CI 工作流接入完成，全部行为 AC 均满足。
- 测试：本地全量门禁套件全部通过；CI YAML 语法校验无误。
- 黑盒：多分层测试命令端到端可执行且均可在单机环境重放。
- review：`review_code.md` PASS，`review_test.md` PASS。
- AC 证据：`.github/workflows/`、`docs/blueprint/testing.md` 与本地测试终端输出。

### 结果摘要

创建了 GitHub Actions CI 与定时扩展工作流，将模板契约、前端工程、桌面打包、真实数据库与协议集成、全栈端到端自动化、数据库迁移、备份恢复演练与性能基准完整统合入本地与远端分层门禁体系中。
