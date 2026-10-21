# p007 设置页通用选项受控状态未随服务端响应回填且空值保存易判定为无改动

- 现象：打开设置模态框切换至「通用」标签页时，时区和拉信超时两个输入框直接回退到 `savedTimezone` / `savedTimeout`，但输入变更时若服务端原配置为空，保存逻辑容易被 `!Object.keys(payload).length` 拦截并提示「没有改动」。
- 影响：设置页（SettingsModal）通用配置的查看与修改体验。
- 根因：`src/frontend/src/components/SettingsModal.tsx` 中 `timezone` 和 `timeoutSeconds` 初始为 `null`，依赖 `timezone ?? savedTimezone` 内联回退，且保存时通过比对与 `saved*` 的差异构造 payload，在初始数据异步加载与输入事件时存在状态脱节。
- 测试缺口：缺少对设置页通用选项修改与回填的端到端交互覆盖测试。
- 线索：`src/frontend/src/components/SettingsModal.tsx:28-34, 235-241`
- 处理：main
