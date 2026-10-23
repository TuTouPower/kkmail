---
tid: "t032"
slug: "sidebar_shell_controls"
title: "整合网页与桌面原生标题栏侧栏控制"
status: "done"
branch: "t032_sidebar_shell_controls"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "1b1407ae5e68ebd732dce46d5386355f9e9b0d56"
depends_on: "t027"
conflicts_with: "t025"
note: "来源：侧栏设计聊天最终要求与 v3 demo；网页列表标题同行控制，macOS 原生红绿灯旁控制，保留移动端 760px 断点; 本批收敛为两个 task；依赖合并后的 t027，原 t028–t031 不再独立调度"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 创建依据：2026-10-23 核对设计聊天、v3 本地原型与 main@26a8eee。
- 实施：网页宽屏将常驻侧栏按钮放入列表标题行；macOS Electron 采用原生 `hidden` 标题栏与 traffic lights，按钮相邻且保留独立拖动区；Windows/Linux 保留原生窗口框架与受控 preload。增加登录/会话检查期间拖动区、主题首帧同步与系统背景色适配。保留全部账号功能与按钮，不实现 demo 的工作/个人分组。
- 实施决策：首次 E2E 检出列表标题垂直对齐、移动遮罩被后置规则隐藏、测试采样时序问题；修正标题按钮对齐与遮罩 CSS，改用模块执行前的 HTML 采样。另补登录页/会话检查态拖动区。macOS 标题栏从 `hiddenInset` 调整为 Electron 官方自定义标题栏采用的 `hidden`；CUA 未验证实际窗口位移。用户于 2026-10-23 明确裁定按通过结束，AC-004 作为用户验收豁免处理，不将其写成实际位移实测。
- 验证：模板契约 149 passed；PostgreSQL 全量 405 passed；前端 39 文件 / 220 passed、类型检查、生产构建、lint、OpenAPI、CSS token 全通过；前端 E2E 13 passed；桌面 `npm test` 通过。最终 `hidden` 样式下实测原生交通灯、侧栏切换、全屏进出、最小化/恢复、关闭/重开与 resize；AC-004 按用户裁定验收通过。Windows/Linux 未提供运行环境，按窗口参数单测核验，未宣称实际平台验证。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 3 (2026-10-23T08:39:41+08:00)

|finding_id|severity|status|rationale|fix_ref|
|---|---|---|---|---|
|t032_gen_f001|important|撤回|用户明确裁定 AC-004 按通过结束；验收豁免已记档，CUA 未实测位移|docs/archive/tasks/t032_sidebar_shell_controls/macos_window_validation.md:20|
|t032_gen_f002|minor|已修|Blueprint 已改为 `hidden`，与最终窗口选项一致|docs/blueprint/conventions.md:75|

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：所有 AC 按用户裁定验收完成；AC-004 采用用户验收豁免，未声称 CUA 实测位移。Win/Linux 原生窗口仅通过窗口参数单测核验，本机无对应运行环境。
- 测试：模板契约 149 passed；PostgreSQL 全量 405 passed；前端 39 文件 / 220 passed；TypeScript、生产构建、lint、OpenAPI、CSS token 检查通过；桌面 `npm test` 通过。
- 黑盒：浏览器 E2E 13 passed；macOS Electron 最终 `hidden` 样式下的原生控件、全屏、最小化/恢复、关闭/重开与 resize 已观察；CUA 未测出窗口位移，AC-004 按用户明确裁定验收通过。详情见 [`macos_window_validation.md`](macos_window_validation.md)，截图留存于本次执行会话。
- review：Round 4 PASS（scope `46c5463ca7cdfe70`）；f001 按用户验收豁免撤回，CUA 未观察到实际位移；f002 已修，本轮无新增 finding。
- AC 证据：见 `handoff.json`

### 结果摘要

- 网页宽屏、移动抽屉、Mac 原生标题栏与主题行为已落地；未减少账号功能按钮，也未把 demo 的“工作/个人”分组写入产品。
- 遗留：无。
