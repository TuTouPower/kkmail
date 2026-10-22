---
tid: "t025"
slug: "desktop_clipboard_copy"
title: "修复桌面端 UI 引用与诊断日志安全复制"
status: "done"
branch: "t025_desktop_clipboard_copy"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "9454a1d2cc9412caf86c5381b427619fdb661a86"
depends_on: ""
conflicts_with: ""
note: "来源 p019；真实 Electron 点击触发 clipboard-sanitized-write 被拒；覆盖两个复制入口及权限边界"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

来源 p019。2026-10-23 真实 Electron 聚焦窗口及鼠标点击复现 request:clipboard-sanitized-write 被生产 hardening 拒绝。两个复制入口统一纳入范围；因涉及权限边界使用 full review。
用户指示在当前 task 一并补齐桌面主进程日志支持（`desktop.log`），捕获主进程启动阶段与未捕获异常，纳入 AC-005。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-23T03:30:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`npm test`（前端 38 文件 184 用例全通，桌面 paths/hardening/postgresManager/startup/logRotation/desktopLog/clipboard 全通，模板契约 149 项全通）
- 黑盒：`npm --prefix src/frontend run test:e2e`（3 项冒烟全通，4.4s）
- review：full review（code + test 均 PASS）
- AC 证据：见 `handoff.json`

### 结果摘要

- AC-001：桌面应用内点击 UI 编号浮标复制结构化引用格式文本，成功反馈且不触发底层控件。
- AC-002：桌面错误边界中点击复制诊断日志成功写入系统剪贴板，保留现有脱敏逻辑。
- AC-003：建立最小权限边界，仅对受信任本地顶层应用页面开放 `clipboard-sanitized-write`；邮件沙箱 iframe、外部来源、剪贴板读取与媒体权限均被严格拒绝。
- AC-004：Web 与桌面双环境剪贴板调用兜底异常，API 缺失与拒绝均给出明确失败反馈且不导致组件二次崩溃。
- AC-005：补齐桌面主进程日志基础设施 `desktop.log` 并接入自动轮转，捕获主进程启动参数、生命周期与未捕获异常。
