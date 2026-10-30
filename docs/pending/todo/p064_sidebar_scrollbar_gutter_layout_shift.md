# p064 侧边栏滚动条显隐挤占宽度引发内容布局跳动

- 现象：当侧边栏内容增多触发垂直滚动条时，滚动条会侵占容器内部可用宽度。用户点击账号列表左侧折叠/展开按钮时，侧边栏高度变化导致右侧滚动条频繁出现或消失，所有菜单项、按钮文字与图标随之发生明显的左右移位与跳动（Layout Shift）。
- 影响：破坏侧边栏（`Sidebar.tsx`）的视觉稳定性，尤其在长账号列表或多文件夹层级展开/折叠时频繁劣化交互体验。在“始终显示滚动条”的系统配置（Windows、Linux 或 macOS 显式设置）下尤为明显。
- 根因：
    1. `src/frontend/src/design-system/components.css:111-118` 的 `.sidebar-scroll` 定义了 `overflow: auto;`，但未设置 `scrollbar-gutter: stable;`。
    2. 浏览器在无内容溢出时不为滚动条预留槽位（gutter），一旦内容高度超过视口即动态向内挤压可用宽度（约 12-16px），导致内容盒尺寸突变。
        同类位点清单：
    - `src/frontend/src/design-system/components.css:948` `.mail-list-scroll`
    - `src/frontend/src/design-system/components.css:1441` `.reader-scroll`
    - `src/frontend/src/design-system/components.css:760` 设置模态框滚动区
- 测试缺口：
    1. 现有前端测试基于 jsdom，不计算真实布局盒模型与滚动条渲染宽度，无法在单元测试中捕捉 layout shift。
    2. Playwright E2E 仅验证了折叠按钮点击后节点的存在与属性变更，未断言元素在展开前后的 `getBoundingClientRect().width` 稳定性。
- 修复方向：
    1. 在 `.sidebar-scroll` 样式中增加 `scrollbar-gutter: stable;`，使容器始终预留滚动条槽位，消除显隐时的宽度抖动。
    2. 对邮件列表与详情阅读区按需应用相同机制，确保全站滚动体验一致。
- 线索：
    - 复现方式：在 macOS「系统设置 → 外观 → 显示滚动条」设为「始终」，进入 kkmail 展开/折叠账号列表，观察「所有邮件」等菜单项的右边界跳动。
- 处理：未开
