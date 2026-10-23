# p029 调整深色模式侧边栏、邮件列表、邮件详情三栏背景色及全局衍生背景色阶

- 来源：用户提出
- 内容：
    1. 核心三栏背景色需求（左到右层级递进，深冷青灰调）：
        - 侧边栏（Sidebar）：`#1C1F21`（原 `--sidebar: #1E1E1E`）
        - 邮件列表（Message List）：`#212628`（原 `--list: #212124`）
        - 邮件详情（Message Reader）：`#222729`（原 `--reader: #1A1A1C`）
    2. 全局其他背景与表面色阶配套联动：
        - 新色值具有一致的冷青灰偏色特征（R 偏低，G/B 略高），且三栏呈现左暗右明的递进关系。
        - 全局其他背景/表面色需参考该基调联动适配：
            - `--canvas`（原 `#171819`，窗口与全局画布底色）及 Electron 桌面端 `windowBackgroundColor` 同步调为比侧栏更深的冷底色；
            - `--surface`（原 `#27292B`，浮层、弹窗、下拉卡片）微调对齐冷青灰高阶；
            - `--surface-2`（原 `#303235`，输入框、次级表面底色）同步微调；
            - `--surface-hover`（原 `#2A2A2E`，侧栏与列表悬停态）同步微调；
            - `--selected`（原 `#323236`，失焦列表选中态）同步微调；
            - `--line` / `--line-strong`（原 `#2C2C2E`，分割线与边框）微调为冷灰系；
            - `--mail-body`（原 `#1A1A1C`）及 `MessageReader.tsx` / `mailBody.ts` 中的默认自适应正文背景，同步对齐 `--reader`（`#222729`）。
    3. 涉及范围：
        - 样式定义：`src/frontend/src/design-system/tokens.css`
        - 邮件渲染：`src/frontend/src/components/MessageReader.tsx`、`src/frontend/src/lib/mailBody.ts`
        - 桌面窗口：`src/desktop/windowOptions.js`
        - 单元测试覆盖：`src/frontend/src/design-system/darkTheme.test.ts`、`src/frontend/src/lib/mailBody.test.ts`、`src/desktop/windowOptions.test.js`
- 处理：t047
