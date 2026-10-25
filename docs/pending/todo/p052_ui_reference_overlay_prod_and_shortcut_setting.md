# p052 前端元素序号浮层生产环境被禁用且缺少快捷键自定义配置

- 现象：
    1. 用户按下快捷键后无法显示所有前端元素序号（此前开发的功能在生产环境无反应）；
    2. 应用设置（`SettingsModal.tsx`）中缺少前端元素序号显示模式（UI Reference Overlay）的快捷键配置与开关入口。
- 影响：
    - 生产环境/打包环境下无法唤出前端元素序号覆盖层（`UiReferenceOverlay`），影响缺陷反馈与控件快速定位；用户无法根据按键习惯调整触发快捷键。
- 根因：
    - `src/frontend/src/App.tsx`（行 20-22）中使用了 `import.meta.env.DEV ? lazy(...) : null`，在生产构建时直接将 `UiReferenceOverlay` 置空丢弃，导致生产环境该功能完全消失；
    - `src/frontend/src/lib/uiReference.ts`（行 62-68）硬编码了快捷键 `Ctrl/Cmd + Shift + .`，未在 `mailStore` 中持久化快捷键偏好，也未在 `SettingsModal.tsx`（“通用”或新增设置卡片）提供修改与录入界面；
    - 已扫无同类。
- 测试缺口：
    - `UiReferenceOverlay.test.tsx` 仅单独挂载 `<UiReferenceOverlay />` 组件测试快捷键触发，未测试在生产环境（`import.meta.env.PROD`）下的加载逻辑；
    - `SettingsModal.test.tsx` 缺少快捷键配置项的读取与修改覆盖。应在端到端或设置页单元测试中补充快捷键配置和生效断言。
- 线索：`.scratch/reproduce_sidebar_and_shortcut.js`
- 处理：未开
