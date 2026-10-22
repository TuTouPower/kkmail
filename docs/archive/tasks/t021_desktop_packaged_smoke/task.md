---
tid: "t021"
slug: "desktop_packaged_smoke"
title: "验证桌面实际打包产物与内置 PostgreSQL 生命周期"
status: "done"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: ""
conflicts_with: ""
note: "本会话批准测试增强；本地复用专用 PG 容器、每轮独立测试库；仅创建 backlog"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

2026-10-22 desktop npm test 通过但 real start/stop skipped；核实 pack-linux.js 的 stub 和 soft-exit 边界。创建阶段不下载二进制、不打包发布。

### 2026-10-22 主分支执行

- 用户明确要求直接在 main 分支按顺序执行 t013–t023，每完成一个 task 独立 commit。
- 修复构建工具链：在 `src/desktop/package.json` 中将 Electron 范围依赖版本固定为 `"44.9.2"`，运行 `npm install` 保证 electron-builder 准确解析对应平台预编译组件。
- 修复 `scripts/fetch-pg-binaries.sh` 中退出 trap 处理 `TMP` 变量在严格模式下的未绑定错误。
- 新增严格打包冒烟测试 `src/desktop/scripts/packaged-smoke.js`（`npm run test:packaged`）：
    - AC-001：断言包内 `frontend/dist/index.html` 为真实生产 SPA，拒绝 stub；核验 `pgsql/bin` 下原生 `initdb`、`pg_ctl`、`postgres` 二进制及匹配的 CPU 架构（如 arm64）；
    - AC-002：在独立隔离目录测试运行包内原生 PostgreSQL 二进制，成功完成首启 `initdb` 和监听端口绑定；
    - AC-004：优雅停止服务，断言监听端口完全释放，子进程全部退出；
    - AC-003：在同一数据目录重新启动，验证数据库不会被重新初始化，持久化密码文件（0600）与状态完好继承；
    - AC-005：测试结束后清理临时测试目录，不触碰生产目录或全局环境。
- 门禁通过：`npm run test:packaged` 顺利通过；`npm test` 基础单元测试全通。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

- 已修：Electron 固定依赖与安装；
- 已修：PostgresManager 返回结构匹配；
- 双人审查（code + test）结论均 PASS。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：桌面实际打包产物与内置 PostgreSQL 生命周期验证闭环，全行为 AC 均满足。
- 测试：`npm run --prefix src/desktop test:packaged` 全通；`npm run --prefix src/desktop test` 6 passed。
- 黑盒：真实 `--dir` 解包 App 产物 -> 校验前端真实生产构建 -> 驱动包内嵌入式 PostgreSQL 首启 initdb、停止释放端口、重启持久化验证。
- review：`review_code.md` PASS，`review_test.md` PASS。
- AC 证据：`src/desktop/scripts/packaged-smoke.js` 终端实测输出。

### 结果摘要

建立了针对桌面实际打包产物的严格校验体系与独立冒烟入口，不仅验证了打包产物内部真实前端 SPA 和平台架构匹配的原生 PostgreSQL 二进制（坚决拒绝 stub），更在独立测试数据目录下完整实测了内置数据库的初始化、启停、端口释放与重启数据持久化。
