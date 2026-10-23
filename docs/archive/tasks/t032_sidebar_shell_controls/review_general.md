# Task review t032（reviewer_focus: 通用）

- task：`t032_sidebar_shell_controls`
- spec：`docs/tasks/t032_sidebar_shell_controls/spec.md`
- diff_anchor：`1b1407ae5e68ebd732dce46d5386355f9e9b0d56`
- target：`git -C '[REDACTED_LOCAL_PATH]' diff 1b1407ae5e68ebd732dce46d5386355f9e9b0d56`
- round：1
- reviewed_at：2026-10-23T08:28:27+08:00

reviewed_scope: 3e2a0d838fcff170

## Findings

### t032_gen_f001 - AC-004 最终窗口样式缺少原生拖动与控件验收证据

- 严重度：important
- 锚点：AC-004 要求实际拖动标题栏空白移动窗口，并在原生窗口操作和 resize 后保持导航可用。
- 位置：`docs/tasks/t032_sidebar_shell_controls/macos_window_validation.md:13`、`docs/tasks/t032_sidebar_shell_controls/macos_window_validation.md:16`
- 问题：最终 `titleBarStyle: 'hidden'` 下，记录显示 CUA 拖动前后 `BrowserWindow` bounds 未变；独立 Electron 样例也未被同一 CUA 操作移动，因此现有工具结果不能证明生产窗口拖动失败，也不能证明 AC-004 通过。记录还说明最小化、关闭和 resize 仅在此前 `hiddenInset` 样式下测试，未在最终 `hidden` 样式复跑。AC-004 的实际窗口移动及部分最终样式行为仍未验证。
- 建议：使用能移动 macOS 原生窗口并读取屏幕坐标的手动或自动化方式，在最终 `hidden` 样式下确认拖动前后 bounds 变化；同时复验最小化、关闭/重开及 resize 不重叠，并记录结果。

### t032_gen_f002 - Blueprint 标题栏样式与最终实现不一致

- 严重度：minor
- 锚点：文档与实现一致性。
- 位置：`docs/blueprint/conventions.md:75`、`src/desktop/windowOptions.js:27`
- 问题：Blueprint 规定 macOS 使用 `hiddenInset`，最终窗口选项使用 `hidden`。按 Blueprint 维护桌面标题栏时会采用与已验证实现不同的标题栏模式。
- 建议：将 Blueprint 更新为 `hidden`，并保留系统交通灯和拖动区边界说明。

## 结论

- 本轮新发现：2 条。
- 未进表的提示：Windows/Linux 未进行实际 Electron 运行；`handoff.json` 与 macOS 验证记录已明确披露，仅验证了窗口选项单测，因此不宣称这些平台已实测。无安全、性能或资源方面的新增问题。
- 总体判断：AC-004 的实际窗口拖动未被证明，且最终标题栏样式下的最小化、关闭和 resize 未复验；important finding 未解决，判 FAIL。`show: false` 配合 `ready-to-show` 让页面完成首帧后才显示窗口；主题 bootstrap 在应用模块前读取保存主题，未发现 AC-007 的首帧错色缺陷。Electron preload 仅增加平台提示，未扩展特权 API。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：`re_verified`。独立运行 `tests/e2e/sidebar_tree.spec.ts`，9 项通过；标题同行、展开/收起、aria 状态、侧栏 DOM 移除与恢复均有断言。
- AC-002：`re_verified`。同一 E2E 检查完整移除侧栏 DOM 与恢复入口；代码中折叠只切换 `sidebarCollapsed`，未改写列宽，导航展开状态仍来自现有持久化 store。
- AC-003：`trust_prior`。未独立操作原生窗口；依赖 `macos_window_validation.md:11-12` 的最终样式记录及执行会话内截图，记录称原生交通灯与按钮相邻且收起侧栏后可恢复。
- AC-004：`trust_prior`。未能独立验证原生拖动；依赖 `macos_window_validation.md:13-16` 的 bounds、最终样式及操作记录。该记录明确实际移动未验证，不能据此将 AC 记为通过。
- AC-005：`trust_prior`。本机无法运行 Windows/Linux；独立运行 `src/desktop` 的 `npm test` 通过，窗口选项测试确认非 macOS 未设置自定义标题栏参数，并检查 contextIsolation、sandbox 与 nodeIntegration；实际系统控件仍未独立验证。
- AC-006：`re_verified`。`tests/e2e/sidebar_tree.spec.ts` 的 9 项通过，覆盖 760px 边界、抽屉遮罩、Escape、选中导航和焦点恢复。
- AC-007：`re_verified`。独立运行前端测试 220 项通过及侧栏 E2E 9 项通过；首帧测试在应用模块执行前读取已保存主题，最终 BrowserWindow 等 `ready-to-show` 后显示，按钮颜色由主题变量控制。
- coverage = 4 / 7
- 建议合并前人工抽查 trust_prior 项。

verdict: FAIL

## Round 2 (2026-10-23T08:32:27+08:00)

reviewed_scope: 1097da8961702aec

## Findings

本轮无新增 finding。

## 结论

- 前轮 finding 复核：`t032_gen_f001` 仍存在。最终 `hidden` 样式下，最小化/恢复、关闭/重开和 resize 已有实际操作记录；但 `macos_window_validation.md:13-14` 明确记录 CUA 拖动前后 bounds 未变，且该工具对独立 Electron 样例也无法拖动，故实际窗口移动仍未验证，AC-004 未闭环。该 finding 只保留此验证缺口，不断言生产拖动实现已失败。`t032_gen_f002` 已消除：`docs/blueprint/conventions.md:75` 已改为 `hidden`，与 `src/desktop/windowOptions.js:27` 一致。
- 本轮新发现：0 条。
- 未进表的提示：Windows/Linux 未实机运行，范围说明仍明确披露，仅有窗口参数单测；未宣称跨平台实测。未发现新安全、性能或资源问题。
- 总体判断：AC-004 要求的实际窗口移动仍无可用验证证据，important finding 未解决，判 FAIL。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：`re_verified`。独立运行侧栏 E2E 9 项通过；最终实现的网页按钮同行、展开/收起、aria 状态和 DOM 行为均有断言。
- AC-002：`re_verified`。E2E 检查侧栏完整卸载及恢复入口；代码保留列宽状态，导航折叠状态仍由持久化 store 提供。
- AC-003：`trust_prior`。无法独立操作原生窗口；依赖 `macos_window_validation.md:11-12` 的最终 `hidden` 样式记录和执行会话截图。
- AC-004：`trust_prior`。依赖 `macos_window_validation.md:13-16` 的 bounds 和最终窗口操作记录；记录表明最小化/恢复、关闭/重开、resize 与全屏已验证，但实际拖动未验证，因此此 AC 仍未通过。
- AC-005：`trust_prior`。本机无 Windows/Linux 运行环境；独立运行 desktop `npm test` 通过，窗口选项测试确认非 macOS 不使用自定义标题栏，实际平台控件仍未独立确认。
- AC-006：`re_verified`。侧栏 E2E 9 项通过，覆盖 760px 边界、遮罩、Escape、选中导航和焦点恢复。
- AC-007：`re_verified`。前端 220 项测试及侧栏 E2E 9 项通过；主题 bootstrap、主题变量及 `ready-to-show` 首帧路径与上一轮复核一致。
- coverage = 4 / 7
- 建议合并前人工抽查 trust_prior 项。

verdict: FAIL

## Round 3 (2026-10-23T08:42:09+08:00)

reviewed_scope: 29c6fc81b91022d0

## Findings

本轮无新增 finding。

## 结论

- 前轮 finding 复核：`t032_gen_f001` 同意撤回。用户明确裁定 AC-004 按通过结束并接受验收豁免；该决定记入 `docs/archive/pending/p023_macos_sidebar_drag_validation.md`，任务记录也标明这是豁免。CUA 未观察到窗口位移，仍不把它写成实测通过；用户接受当前实现并豁免该证据后，f001 不再阻断收尾。`t032_gen_f002` 已修：`docs/blueprint/conventions.md:75` 的 `hidden` 与 `src/desktop/windowOptions.js:27` 一致。
- 本轮新发现：0 条。
- 未进表的提示：Windows/Linux 未进行实际 Electron 运行；`handoff.json` 和 macOS 窗口记录已披露，仅验证窗口参数单测。未宣称跨平台实测。无新增安全、性能或资源问题。
- 总体判断：用户已接受 AC-004 的验收豁免；f001 按用户裁定撤回，f002 已修，本轮无未解决 critical/important finding，判 PASS。CUA 未观察到实际窗口位移这一事实保留在黑盒记录中。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：`re_verified`。独立运行侧栏 E2E 9 项通过；标题同行、展开/收起、aria 状态、侧栏 DOM 移除和恢复均有断言。
- AC-002：`re_verified`。E2E 检查侧栏完整卸载及恢复入口；代码保留列宽状态，导航折叠状态由持久化 store 提供。
- AC-003：`trust_prior`。无法独立操作原生窗口；依赖 `macos_window_validation.md:11-12` 的最终 `hidden` 样式记录和执行会话截图。
- AC-004：`trust_prior`。`macos_window_validation.md:13-16,20` 说明 CUA 未观察到窗口位移；依照用户明确验收豁免，将 AC-004 按通过结束，不把该项计作实际位移实测。
- AC-005：`trust_prior`。本机无 Windows/Linux 运行环境；独立运行 desktop `npm test` 通过，窗口选项测试确认非 macOS 不使用自定义标题栏，实际平台控件仍未独立确认。
- AC-006：`re_verified`。侧栏 E2E 9 项通过，覆盖 760px 边界、遮罩、Escape、选中导航和焦点恢复。
- AC-007：`re_verified`。前端 220 项测试及侧栏 E2E 9 项通过；主题 bootstrap、主题变量与 `ready-to-show` 首帧路径复核通过。
- coverage = 4 / 7
- 建议合并前人工抽查 trust_prior 项。

verdict: PASS

## Round 4 (2026-10-23T08:45:55+08:00)

reviewed_scope: 46c5463ca7cdfe70

## Findings

本轮无新增 finding。

## 结论

- 前轮 finding 复核：`t032_gen_f001` 继续按用户验收豁免撤回。`docs/archive/tasks/t032_sidebar_shell_controls/task.md:40` 与 `docs/archive/pending/p023_macos_sidebar_drag_validation.md:4` 记录了用户裁定；`macos_window_validation.md:13,20` 仍明确说明 CUA 未观察到窗口位移，报告不将其写成实测通过。`t032_gen_f002` 已修：`docs/blueprint/conventions.md:75` 的 `hidden` 与 `src/desktop/windowOptions.js:27` 一致。
- 本轮新发现：0 条。
- 未进表的提示：Windows/Linux 未进行实际 Electron 运行，handoff 明确只验证窗口选项单测。Finalization 累积的 `docs/specs/inbox_ui_and_search.md` 将 AC-004 用户验收豁免和未观察到的 CUA 位移如实记载；未发现新增安全、性能或资源问题。
- 总体判断：f001 已按用户明确决定撤回，f002 已修；无未解决 critical/important finding，判 PASS。AC-004 的实际位移仍未被 CUA 观察到，按用户裁定验收豁免结束，不视为实际位移实测通过。
- 系统性 follow-up：无。

### AC 复验方式

- AC-001：`re_verified`。侧栏 E2E 9 项通过，覆盖标题同行、aria 状态、折叠时 DOM 移除与恢复。
- AC-002：`re_verified`。E2E 检查侧栏完整卸载和恢复入口；列宽状态不因折叠改变，导航展开状态由持久化 store 提供。
- AC-003：`trust_prior`。无法独立操作原生窗口；依赖 `macos_window_validation.md:11-12` 的最终 `hidden` 样式记录和执行会话截图。
- AC-004：`trust_prior`。依赖 `macos_window_validation.md:13-16,20` 与用户验收豁免记录；CUA 未观察到实际窗口位移，按用户裁定验收通过，不声称位移已实测。
- AC-005：`trust_prior`。本机无 Windows/Linux 运行环境；独立 desktop 单测验证窗口选项保留默认框架和现有安全设置，实际平台控件未独立确认。
- AC-006：`re_verified`。侧栏 E2E 9 项通过，覆盖 760px 边界、遮罩、Escape、选中导航和焦点恢复。
- AC-007：`re_verified`。前端 220 项测试及侧栏 E2E 9 项通过；启动主题读取、主题 token 和 Electron `ready-to-show` 显示路径均已复核。
- coverage = 4 / 7
- 建议合并前人工抽查 trust_prior 项。

verdict: PASS
