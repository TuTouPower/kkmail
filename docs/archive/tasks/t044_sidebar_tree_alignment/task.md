---
tid: "t044"
slug: "sidebar_tree_alignment"
title: "修复侧边栏顶层按钮与多层级树几何对齐"
status: "done"
branch: "t044_sidebar_tree_alignment"
worktree: ""
review_level: "single"
review_limit: "5"
verify_limit: "5"
diff_anchor: "2fc7335da1d57ac980a59fc3b0acd4b32f659d81"
depends_on: ""
conflicts_with: ""
note: "来源 p026；统一顶层标题与子层级缩进网格并补齐 Playwright 几何坐标断言。"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

1. 诊断与复现：通过 Playwright 在真实 Chromium 视口测量发现，“所有账号”、“分组”、“账号列表”顶层标题因 DOM 结构嵌套（内部按钮叠加 padding 与 gap）导致展开箭头偏差 4px、图标偏差 8px、文本偏差 12px；Level 1 分类与账号兄弟行图标偏差 3px；Level 2 文件夹与分类下账号缺失折叠槽位占位，导致图标列与父级重合在 58px（0px 相对缩进）；表单与加载错误行未对齐所属父层级。
2. 架构重构与对齐：
   - 统一顶层标题 DOM 与样式结构：将“所有账号”改造为外层 div 包含 `tree-disclosure` 与 `tree-heading-main`，与各“分组”及“账号列表”完全一致；统一容器 `gap: 4px` 与主按钮 `padding: 0 4px 0 0; gap: 8px`，使三者的 chevron（14px）、icon（36px）、text（60px）完全像素级对齐（<= 1px 误差）。
   - 统一子层级网格与阶梯缩进：在 Level 2 叶子行（`tree-folder-row`、`tree-category-account`）补充 `tree-disclosure-slot` 占位，统一 `AccountIcon`（`.account-dot`）在树节点中为 16px，使 Level 1 兄弟节点（分类与账号）完全水平对齐，Level 2 子节点相对父节点形成严格 24px 阶梯缩进，子级图标列严格位于父级图标列右侧。
   - 统一辅助状态与表单缩进：新建/重命名分组内联表单调整为 `padding: 4px 4px` 对齐 Level 0；账号加载与错误提示设置 `padding-left: 24px` 对齐 Level 1；文件夹加载与错误状态设置 `padding-left: 48px` 对齐 Level 2。
3. 测试验证：
   - 在 `tests/e2e/sidebar_tree.spec.ts` 中新增真实浏览器渲染几何断言（`boundingBox.x`），逐条覆盖 AC-001 ~ AC-004，并重跑全量前端单测、类型检查、构建与全栈端到端测试。

## Review 处置

### Round 1 (2026-10-23T21:55:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`(cd src/frontend && npm test && npx tsc -b && npm run build && npm run lint)` 全通；`(cd src/desktop && npm test && npm run test:packaged)` 全通；`pytest .repo_template/tests -q -m contract` 全通；`scripts/run-mail-core-tests.sh unit` 304 passed。
- 黑盒：`npm --prefix src/frontend run test:e2e`（14 项全部通过，包含 t044 像素几何对齐与缩进新用例）；`python3 scripts/run_full_stack_e2e.py`（8 项全栈真实端到端测试全部通过）。
- review：`docs/tasks/t044_sidebar_tree_alignment/review_general.md` 单轮 PASS，0 finding。
- AC 证据：见 `handoff.json`

### 结果摘要

- 修复侧边栏顶层三大标题及多级子树水平几何对齐与阶梯缩进，对齐误差控制在 1px 以内，完成端到端自动化几何坐标断言守护并更新架构规范。遗留：无。
