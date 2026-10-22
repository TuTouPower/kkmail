# p019 UI 编号引用与诊断日志在桌面端点击复制报错「剪贴板不可用或未获授权」

- 现象：通过快捷键（`⌘ + Shift + .` / `Ctrl + Shift + .`）开启 UI 引用覆盖层后，点击任意控件标签（如 `SB05`），右下角弹出错误「复制失败：剪贴板不可用或未获授权」，引用文本未写入系统剪贴板。
- 影响：UI 稳定编号模式无法复制控件引用；同类位点 `ErrorBoundary` 错误边界中的「复制诊断日志」在桌面端同样必定复制失败。
- 根因：
    - 核心机制：`src/desktop/hardening.js` 中 `denyPermissionRequest` 与 `denyPermissionCheck` 为安全加固无条件拒绝所有权限请求；Chromium / Electron 渲染进程调用 `navigator.clipboard.writeText` 触发权限检查（`clipboard-read` / `clipboard-sanitized-write`），被主进程无条件拒绝，抛出 `NotAllowedError: Write permission denied`。
    - 前端缺少降级：`UiReferenceOverlay.tsx` 与 `ErrorBoundary.tsx` 均直接依赖 `navigator.clipboard.writeText`，既未针对 Electron 暴露安全的剪贴板写入通道，也无文本复制降级支持。
    - 同类位点清单：
        1. `src/frontend/src/components/UiReferenceOverlay.tsx`（`handleCopy` 行 112-125）
        2. `src/frontend/src/components/ErrorBoundary.tsx`（`copyReport` 行 30-42）
        3. `src/desktop/hardening.js`（`denyPermissionRequest` / `denyPermissionCheck` 行 35-43）
- 测试缺口：
    - 前端单测（`UiReferenceOverlay.test.tsx` 与 `ErrorBoundary.test.tsx`）运行在 jsdom 下，单测显式 mock 了 `navigator.clipboard` 且直接将“拒绝时展示复制失败提示”作为断言通过项，遮蔽了桌面运行时必定失败的真实缺陷；
    - 桌面加固单测 `src/desktop/hardening.test.js` 仅验证了 `media` 权限被拒，未测试桌面端剪贴板权限与写入行为。
- 线索：`.scratch/reproduce_ui_copy_bug.js`

## 2026-10-23 转办核实

- 当前两个复制入口仍直接调用 `navigator.clipboard.writeText`；preload 无写入能力，桌面生产 permission handlers 仍无条件拒绝。无等价有效 backlog/active task。

- `.scratch/pending_candidate_audit.js` 在当前 Electron 44.9.2 中加载生产 hardening，聚焦窗口并用真实鼠标输入点击；捕获 `request:clipboard-sanitized-write`，结果为 `NotAllowedError: Write permission denied`。已区分隐藏窗口导致的 `Document is not focused`；最终证据使用聚焦窗口，确认并非单纯焦点问题。

- 同类位点仍为 UI 引用和诊断日志两个入口。转 t025，要求真实 Electron 复制验证，并覆盖不可信来源/frame、剪贴板读取与无关权限仍拒绝；不将全局放开权限作为修复。

- 前端 mock 与 hardening helper 单测不能覆盖真实授权链路，t025 明确补测贯通实际复制路径。

- 处理：t025
