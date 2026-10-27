---
tid: "t058"
slug: "centralized_config_and_runtime_params"
title: "重构集中式配置管理与抽离核心运行参数"
status: "done"
branch: "t058_centralized_config_and_runtime_params"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "5fb5f05dadc9da4605a54ab8bc6fc1dc689a3234"
depends_on: "t057"
conflicts_with: ""
note: "依据配置规范建立集中式配置模型并抽离硬编码参数，容纳 t057 收件箱轮询配置，补全 env 示例"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. TDD 建立 `tests/mail_core/test_config.py`，覆盖默认值、环境变量覆盖、连接槽位、存储大小、Worker/调度参数及非法边界校验（AC-001 ~ AC-006）。
2. 实现 `src/mail_core/config/` 模块（`models.py`, `loader.py`, `__init__.py`），提供强类型配置、单例访问及合法性校验。
3. 改造 `src/mail_core/providers/connection_slots.py`、`src/mail_core/blobs/archive.py` 与 `src/mail_core/worker/main.py` 对接集中配置，抽离硬编码参数。
4. 在 `src/mail_core/__main__.py` 首帧触发配置校验。
5. 更新 `src/desktop/startup.js` 与 `startup.test.js` 补齐环境变量白名单（AC-008）。
6. 重写 `config/.env.example` 并更新 `src/mail_core/README.md`（AC-007）。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-27T20:20:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`pytest .repo_template/tests -q -m contract` (189 passed)；`scripts/run-mail-core-tests.sh run -k "test_config or test_provider_connection_slots or test_worker_scheduler or test_delta_archive_integration"` (17 passed)；桌面端 `npm test` 通过；前端测试与构建全部通过。
- 黑盒：`npm --prefix src/frontend run test:e2e` (18 passed)。
- review：code PASS，test PASS，指纹 `470e3f905ef2b928` 匹配。
- AC 证据：见 `handoff.json`

### 结果摘要

- 建立 `src/mail_core/config/` 集中配置管理系统，统一强类型默认值、环境变量覆盖与边界合法性校验。
- 成功抽离外联连接槽位数、后台起始槽位、容量退避延迟、MIME 大小上限、附件大小上限、归档窗口、Worker 领单批次、任务回收周期及收件箱巡检周期。
- 补全 `config/.env.example` 模块化模板与桌面端透传白名单，应用启动首帧强校验拦截非法配置。
