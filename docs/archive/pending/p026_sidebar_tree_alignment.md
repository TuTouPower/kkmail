# p026 修复侧边栏顶层按钮错位及多层级缩进与对齐混乱

- 现象：
    1. 侧边栏顶层的“所有账号”与“账号列表”两个核心按钮未在同一列对齐（以及同为顶层的“分组”标题同样存在偏差）：
        - 展开折叠箭头 x 坐标：所有账号 14px、分组 14px、账号列表 18px（账号列表向右突兀缩进 4px，箭头不对齐）。
        - 标题图标 x 坐标：所有账号 35px、分组 39px、账号列表 43px（分别相差 4px、8px，三大顶层图标水平错位）。
        - 文本标签 x 坐标：所有账号 54px、分组 62px、账号列表 66px（文本水平偏移高达 12px）。
    2. 侧边栏内部子项的对齐与缩进梯级混乱：
        - 同为 Level 1 的兄弟项（分组展开后的“分类项”与“账号项”）：分类项图标位于 61px、文字位于 85px；账号项图标位于 58px、文字位于 84px，兄弟节点之间图标错位 3px、文字错位 1px。
        - Level 2 子项（账号展开后的文件夹项）：文件夹图标位于 58px，与父级账号图标（58px）完全在同一水平列，没有形成阶梯缩进，层级关系在视觉上不清晰；分类展开后的账号项同样缺乏基准网格对齐。
        - 附属行缩进不一：新建分组表单 `padding-left: 24px`，文件夹加载状态 `padding-left: 48px`，账号加载/错误状态仅 `padding: 6px 8px`（完全无左缩进，错位 16px）。
- 影响：
    - 侧边栏全局视觉层级杂乱、各板块左边界和图标列凹凸不平。
    - 用户从“所有账号”切换/查看“账号列表”或“自定义分组”时，展开箭头和图标出现肉眼可见的左右跳动。
    - 子层级缺乏统一的树状对齐基准（Grid/Baseline），破坏树形导航的层级感与可读性。
- 根因：
    1. 顶层标题 DOM 与 CSS 结构层级不一致（可验证机制）：
        - “所有账号”是直接的 `<button className="tree-section-heading">`，外层有 `padding: 0 4px; gap: 3px;`，箭头、图标和文字为直接子元素。
        - “分组”为 `<div className="tree-group-heading">`（`padding: 0 4px; gap: 3px;`），内部展开箭头 `<button className="tree-disclosure">` 是直接子元素，但标题部分嵌套了 `<button className="tree-group-select">`，后者自带 `padding: 0 4px; gap: 7px;`，导致其内部图标和文字额外产生了 4px 和 8px 偏移。
        - “账号列表”为 `<div className="tree-section-heading tree-drop-zone">`（`padding: 0 4px; gap: 3px;`），其内部将展开箭头槽 `.tree-disclosure-slot` 错误嵌套在 `<button className="tree-heading-main">` 内部；而 `tree-heading-main` 自身声明了 `padding: 0 4px; gap: 7px;`，引发箭头双重 padding（偏移 8px），图标和文字进一步累计偏移。
    2. 扫描同类位点清单：
        - 位点 1（Level 1 兄弟项对齐）：`tree-category-heading`（内联 `paddingLeft: 24px` + `gap: 3px` + `tree-nav-row` `gap: 8px`）与 `tree-account-row`（内联 `paddingLeft: 24px` + `gap: 2px` + `tree-account-select` `padding: 0 4px; gap: 7px;`）内部结构和样式不一致，导致同一层级的图标错位 3px。
        - 位点 2（Level 2 子项缩进与无箭头行对齐）：`tree-folder-row` 和 `tree-category-account` 直接通过内联 `paddingLeft: 48px` 粗糙偏移，缺少统一的层级缩进基准（例如：固定 20px 或 24px 阶梯）和展开插槽占位（slot/indent spacer），导致无箭头叶子项与有箭头项图标列混杂。
        - 位点 3（状态与表单行缩进）：`tree-inline-form`（`padding-left: 24px`）、`tree-folder-status`（`padding-left: 48px`）、`tree-loading`/`tree-load-error`（`padding: 6px 8px`，完全缺失 `paddingLeft`），各状态提示与表单没有对齐对应的父层级。
- 测试缺口：
    - `src/frontend/src/components/Sidebar.test.tsx` 运行在 JSDOM 环境中，无法计算真实的 flexbox 布局、CSS 盒模型和 bounding rect，仅能检测文本存在性与点击事件。
    - `tests/e2e/sidebar_tree.spec.ts` 中现有的 E2E 布局测试（第 199 行 `t027` 用例）只做了简单的内联字符串检查（`expect(indent).toBe('24px')`），未对“所有账号”、“分组”、“账号列表”顶层标题以及各层级子项进行精确的几何坐标断言（`boundingBox.x` 比较），导致严重的视觉错位在 CI 门禁中假绿放行。
    - 应补测层级：在 Playwright 端到端测试（`tests/e2e/sidebar_tree.spec.ts`）中增加精确几何对齐断言，验证顶层所有账号、分组、账号列表的 chevron/icon/label x 坐标必须像素级对齐，以及各级子树缩进步长保持一致。
- 线索：
    - `.scratch/repro_sidebar_alignment.spec.ts`：通过 Playwright 测量真实浏览器渲染结果，复现了所有账号（14px, 35px, 54px）、分组（14px, 39px, 62px）、账号列表（18px, 43px, 66px）的错位数据，以及分类与账号子项错位 3px 的真实几何数据。
    - `.scratch/playwright.repro.config.ts`：Playwright 复现运行配置。
- 处理：t044
