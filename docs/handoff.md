# 项目交接记录（最新）

本文件只保留当前有效一节。过时段落由 `repo-hygiene` 迁入 `docs/archive/handoff.md`。

## 2026-10-22T02:48:00+08:00 agent → developer

- 当前焦点：采用 repo_template 模板完成全仓工程化改造、目录架构分流与门禁对齐
- branch：main
- head_commit：784f7a0494cf3e51247ffbe2e684073ae0315da1
- 已完成：
    - 源码收拢：后端、前端与桌面端源码全量收敛至 `src/`（`src/mail_core/`, `src/frontend/`, `src/desktop/`）。
    - 测试归位：E2E 测试从 `src/frontend` 迁出至全局测试目录 `tests/e2e/`，彻底净化源码目录；配置根目录与前端的 Playwright 联动。
    - 契约归位：OpenAPI 模式归入 `schemas/openapi.json`，同步全量脚本与自动化校验。
    - 资产归位：删除废弃皮肤目录 `data/skins/`；所有截图与设计文档收入 `assets/img/` 与 `assets/DESIGN.md`。
    - 配置归位：环境示例迁至 `config/.env.example`，根目录保留便捷软链。
    - 文档重构：长期真相整合写入 `docs/blueprint/`（架构、领域、约定、决策、测试）；人类使用手册规范放入 `docs/guides/`；已决策项全量挪入 `decisions.md` 并清理已做完待办；生成 3 篇带行为 AC 的生效 Spec（`auth_and_session`, `mail_sync_and_storage`, `inbox_ui_and_search`）并登记入 `docs/specs_index.md`。
    - 工具链落地：同步模板源最新提交 `658a825`，生成技能软链与 `.opencode/commands/` 命令薄层，执行 `install-hooks` 激活 `core.hooksPath`。
    - 缺陷修复：解决 Docker 构建中 TypeScript 与 openapi-typescript 的 peer 依赖冲突，修复桌面端与运维脚本中的硬编码旧路径。
- 未完成：无
- 陷阱：
    - 单独运行 Python 脚本或 Alembic 时需确保 `PYTHONPATH=src`（脚本与 env.py 已内置保护，裸跑命令时请留意）。
    - Playwright E2E 测试依赖 `src/frontend/node_modules` 依赖，运行时已自动配置 `NODE_PATH`，请通过 `npm --prefix src/frontend run test:e2e` 执行。
- 下一步：
    - 等待用户最终代码审查，确认无误后执行原子提交与推送。
