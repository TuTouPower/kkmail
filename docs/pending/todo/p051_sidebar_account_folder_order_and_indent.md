# p051 侧栏账号展开后文件夹缩进过深且收件箱排在未读邮件之后

- 现象：
    1. 侧栏展开邮箱账号后，“未读邮件”固定排在整个文件夹树最上方，导致“收件箱”排在“未读邮件”之后，不符合“收件箱排在未读邮件前面”的视觉与使用预期；
    2. 邮箱账号行内的文件夹（“未读邮件”、各级文件夹）相比于上方的邮箱账号行缩进差距过大；在计算缩进层级时，未对齐折叠/展开符号（`tree-disclosure` 与 `tree-disclosure-slot`）的几何基准，且静态叠加了过大的基础 `paddingLeft`（48px），造成视觉层级失衡。
- 影响：
    - 侧栏邮箱账户目录展开（`Sidebar.tsx` 内 `AccountFolders` 与 `renderTree`）下的所有账户文件夹渲染及状态提示（loading、error）。
- 根因：
    - `src/frontend/src/components/Sidebar.tsx` 中 `AccountFolders` 组件将 `<button>未读邮件</button>` 硬编码置于 `{renderTree(roots)}` 前面（行 280-290），而收件箱（role 为 `inbox`）位于 `roots` 内部首位，导致未读邮件在收件箱上方；
    - 账号行 `tree-account-row` 缩进使用 `${depth * 24}px`（depth=1 时为 24px），其内部包含 18px 展开箭头 `tree-disclosure` + 4px gap；而 `AccountFolders` 内无论子节点有无折叠符号，一律强加 `paddingLeft: 48px` 并内嵌 18px `tree-disclosure-slot`，导致起始内容位移达到 `48 + 18 + 8 = 74px`，比账号图标起始位置（`24 + 18 + 4 = 46px`）足足深了 28px，未将展开折叠符号纳入整体缩进对齐计算；
    - 同类位点：
        - `AccountFolders` 中的状态行 `tree-folder-status`（行 218、219、223、225、279）硬编码 `paddingLeft: 48px`；
        - 顶层全局分类下展开的账号列表 `tree-category-account`（行 843）硬编码 `paddingLeft: 48px`。
- 测试缺口：
    - `src/frontend/src/components/Sidebar.test.tsx` 仅断言包含“收件箱”文本及行数，未对子项渲染顺序（收件箱在未读邮件前）以及精确计算的 padding/indent style 做断言；应在组件测试中补充顺序和层级缩进断言。
- 线索：`.scratch/reproduce_sidebar_and_shortcut.js`
- 处理：未开
