---
pid: "p023"
slug: "macos_sidebar_drag_validation"
status: "closed"
resolution: "resolved"
reason: "已在 t032 修复并验证"
fix_ref: "t032"
---
# p023 macOS Electron 标题栏拖动待人工验收

- 来源：t032 遗留（task-run 黑盒门禁未闭环）
- 内容：曾要求在最终 `titleBarStyle: 'hidden'` 样式下拖动标题栏并比较 bounds；CUA `drag()` 未改变生产窗口或最小 Electron 样例 bounds。用户于 2026-10-23 明确裁定按通过结束，接受当前实现作为验收豁免。
- 处理：t032；resolution=resolved；reason=已在 t032 修复并验证
