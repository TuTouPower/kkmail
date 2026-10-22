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
- 处理：未开
