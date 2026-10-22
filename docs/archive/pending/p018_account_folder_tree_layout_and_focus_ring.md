# p018 修复侧栏账号文件夹展开错位、点击蓝色焦点框及历史UTF-7文件夹名解码

- 现象：
    1. 点击侧边栏折叠/展开按钮（如账号或分类旁的 chevron 图标按钮）时，按钮外圈出现突兀的蓝色矩形聚焦边框（`outline: 2px solid var(--accent)`）。
    2. 展开单个邮箱账号查看文件夹时，子文件夹列表（收件箱、已发送、&V4NXPpCuTvY- 等）横向挤在账号右侧并向下溢出，遮挡下方其他账号行。
    3. 网易等 IMAP 账号系统文件夹显示为未解码的 Modified UTF-7 原始字符串（如 `&dcVr0mWHTvZZOQ-`、`&g0l6P3ux-`、`&V4NXPpCuTvY-`、`&XfJSIJZk-`），图标退化为普通文件夹。
- 影响：
    - 侧边栏账号文件夹导航视觉严重错位与遮挡重叠，无法正常查看单个账号的下级文件夹与未读数。
    - 鼠标点击折叠箭头或侧栏按钮时产生残留的蓝色聚焦框，破坏深色/浅色交互体验。
    - 历史账号及网易/IMAP 特殊系统文件夹名称与角色未能正确识别与解码，影响文件夹定位与标题显示。
- 根因：
    1. 布局结构冲突：`Sidebar.tsx` 中将 `<AccountFolderTree>` 直接放置在 `.account-row` 内部，而 `tokens.css` 中 `.account-row` 定义为固定高度且水平伸缩的容器（`height: 33px; display: flex; align-items: center;`），导致文件夹树作为第二个 flex 子项横向排在账号右侧并溢出 33px 容器高；对比 `.favorite-category` 采用块级容器嵌套 header 与子列表。
    2. 焦点环样式未区分鼠标点击与键盘导航：`tokens.css` 定义了全局 `button:focus-visible { outline: 2px solid var(--accent); }`，但未配置 `button:focus:not(:focus-visible) { outline: none; }`，且侧边栏 `.category-toggle`、`.group-toggle` 等图标按钮未抑制鼠标点击时的 outline。在 Chromium / WebKit 桌面端点击按钮后命中焦点导致外圈显示蓝色边框。
    3. 历史文件夹数据与前端容错缺失：
        - 在 t008 引入 `decode_mutf7` 之前入库的历史文件夹（或在未执行重新发现的已有账号中），数据库 `folders` 表保存的 `name` 仍为 IMAP 原始 Modified UTF-7 字符串，`role` 均为 `other`。
        - `JobType.SYNC_ACCOUNT_FOLDERS` 仅在新建账号时入队，日常同步不自动触发全量文件夹重新发现。
        - `list_folder_stats_for_account` 查询未进行读取期解码与角色回退；前端 `Sidebar.tsx` 仅按已知 `role` 做简单 switch，对 `other` 角色直接透传原始 `rawName`，且未内置前端 modified UTF-7 解码兜底。
    4. 已扫描同类位点：
        - 类似折叠结构扫描：`favorite-category`（正常，块级流）、`account-group`（正常，块级流）、`AccountFolderTree` 内部嵌套子目录（采用 `folder-tree-row`，缺少独立样式但为 block）；确认仅 `.account-row` 存在 flex-row 错位。
        - 类似按钮扫描：`.sidebar-toggle`、`.group-toggle`、`.category-toggle`、`.footer-btn`，均继承全局 `:focus-visible` 且缺少点击去边框处理。
        - 类似文件夹名称显示位点：`listTitle.ts` 文件夹标题展示，直接使用 `view.folderName`，若未解码同样会展示乱码。
- 测试缺口：
    - `Sidebar.test.tsx` 仅通过 `expect(acc1Row?.textContent).toContain('收件箱')` 检查文本存在性，未断言 DOM 布局层级（`.account-folders` 位于独立块级容器）、未断言 CSS 容器属性（`.account-row` 不应限制 height 33px 且不应为水平 flex item）。
    - 组件测试使用 JSDOM，未模拟 Chromium 鼠标点击触发焦点环与 `:focus:not(:focus-visible)`。
    - `test_account_folder_navigation.py` 仅用虚拟 IMAP 测试了全新扫描解析，未覆盖已有数据库记录为 UTF-7 原始字符串时的读取与修复，前端 mock 数据也均使用了已解码中文。
- 线索：
    - `.scratch/repro_sidebar_issue.html`（CSS 错位与聚焦边框复现）
    - `.scratch/test_mutf7_decode.py`（163 邮箱真实 Modified UTF-7 文件夹映射验证）

## 2026-10-23 转办核实与纠正

- 布局缺陷仍存在，转 t024：生产 `.account-row` 仍为固定 33px 高水平 flex，树与标题同级；`.scratch/pending_candidate_audit.js` 使用现有 CSS 在真实 Electron 测出树横排并覆盖下一账号。组件单测仅验证文本，缺几何回归。

- 原焦点根因证据不足，撤回“缺少 focus:not(:focus-visible) 必然导致鼠标蓝框”的结论：原复现页含 autofocus；本次真实鼠标点击 outline=none，Tab 后 focus-visible=true/outline=solid。t024 保留键盘焦点与操作回归，不增加全局去焦点重置。其他平台或特定操作序列若仍出现异常，应附新证据再分析。

- 原“只有新建账号才调度全量发现”描述不成立：设置页账号“同步”调用 `/api/accounts/{id}/sync`，经 `sync_account_app` → `enqueue_account_sync` 入队 `SYNC_ACCOUNT_FOLDERS`；`sync_account_folders` 对已有同 remote_id 文件夹更新 name/role/parent_remote_id，复用 t008 的 Modified UTF-7 解码和角色映射。

- 历史文件夹不新增读取期解码、自动修复或额外脚本。优先复用现有显式“同步”；本次仅核实代码链路，未连接生产库、未执行同步，不能声称历史生产记录已修好。需要额外历史修复工具时另行确认范围，禁止因本次转办自动执行数据操作。

- 来源拆分：已确认布局缺陷及导航/键盘回归归 t024；历史名称已有 t008 解码与显式重新发现路径，不重复立项；鼠标焦点根因未证实。无等价有效 backlog/active task。

- 处理：t024
