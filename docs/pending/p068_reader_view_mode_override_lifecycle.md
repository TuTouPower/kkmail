---
pid: "p068"
slug: "reader_view_mode_override_lifecycle"
status: "closed"
resolution: "resolved"
reason: "已在 t066 修复并验证"
fix_ref: "t066"
---
# p068 明确阅读器单信深色覆盖的生命周期并修复单值覆盖

- 来源：t066 创建前审阅（Codex）承接原 p066 同类位点；`src/frontend/src/components/MessageReader.tsx:82`
- 内容：`viewModeOverride` 当前为单个 `{ key, mode }` 组件局部 state，只保留最后操作的邮件；切换邮件后原邮件的“原样/深色”覆盖丢失或被覆盖，刷新页面也会丢失。需先确认产品语义：单信覆盖应仅当前会话、按邮件分别保留，还是像正文深色偏好一样持久化；随后改为按邮件 ID 管理的状态并补测多邮件切换、unmount/remount 与刷新行为。t066 仅处理远程图片放行，不扩大范围，故未一并实施。
- 处理：t066；resolution=resolved；reason=已在 t066 修复并验证
