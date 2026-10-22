# p012 深色模式界面与阅读区背景色对齐 Apple Mail

- 来源：用户提出（附 Apple Mail 原生深色模式界面实测对比）
- 内容：
    1. 当前问题：
        - 当前深色模式三栏色阶（`--sidebar: #1C1D1F`、`--list: #202123`、`--reader: #1D1F20`）整体均在 `#1C~#20` 范围，缺乏原生 macOS Apple Mail 阶梯反差，呈现浑浊灰感；
        - 邮件列表选中高亮使用的是暗沉灰色 `#34383D`，而非 Apple 原生鲜明聚焦蓝 `#0A60FE`；
        - 阅读区正文背景被硬编码为 `--mail-body: #fff`，暗黑模式下呈现突兀大白块。
    2. Apple Mail macOS 原生深色模式精确色值定义（执行时直接采用以下具体 Hex，无需推测）：
        - **三栏背景色阶（从左到右层级递进）**：
            - 左栏 侧边栏（Sidebar）：`#1E1E1E`（沉浸深灰，窗口材质基底）
            - 中栏 邮件列表（Message List）：`#212124`（中度高灰，凸显列表层级）
            - 右栏 邮件阅读区容器（Reader）：`#1A1A1C`（深沉背景）
            - 邮件阅读正文底色（Mail Body）：纯文本与深色自适应邮件为 `#1A1A1C`；浅色固定富文本邮件以独立纸张卡片承载（背景 `#FFFFFF`、内边距与圆角隔离），外层容器保持 `#1A1A1C`，消除全屏生硬通栏白块。
        - **状态与交互色值**：
            - 列表项悬停（Hover）：`#2A2A2E`
            - 列表项聚焦选中（Focused Selected）：`#0A60FE`（Apple 经典系统亮蓝）
            - 列表项失焦选中（Unfocused Selected）：`#323236`
            - 选中态文字颜色：纯白 `#FFFFFF`，时间与副标题变为 `#D0E2FF`
            - 未读指示圆点（Unread Dot）：`#0A84FF`
            - 分割线与边框（Border / Line）：`#2C2C2E`（1px 实线，轻微半透明感知）
        - **文字与图标色阶**：
            - 主文本（Primary Text / 发件人）：`#FFFFFF`（高对比，font-weight 600）
            - 次级文本（Secondary Text / 主题）：`#E4E4E6`
            - 辅助文本（Tertiary Text / 时间 / 摘要）：`#8E8E93`
            - 弱化图标与折叠指示（Icons）：`#98989D`，悬停 `#FFFFFF`
    3. 待修改位点：
        - `src/frontend/src/design-system/tokens.css` 中 `html[data-theme="dark"]` 的 CSS 变量；
        - `assets/DESIGN.md` 中的设计规范常量；
        - `src/frontend/src/components/MessageReader.tsx` 与 `src/frontend/src/lib/mailBody.ts` 中正文 iframe 的背景与深色卡片模式。
- 处理：未开
