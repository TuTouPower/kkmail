# Task spec

## 背景

深色模式当前三栏背景色（侧边栏 `#1E1E1E`、列表 `#212124`、阅读器 `#1A1A1C`）缺乏从左到右统一的冷青灰层级递进关系；同时阅读器与列表在邮件缺失发件人或收件人时显示“未知”、“未提供”占位词，以及阅读器正文未完成同步时提示“邮件正文尚未完成同步或内容为空 / 该邮件没有正文内容或内容为空。”，文案含糊且存在多余占位文字。

## 契约区

### 范围

- 调整深色模式核心三栏背景色为从左到右递进的深冷青灰调：侧边栏 `--sidebar: #1C1F21`、邮件列表 `--list: #212628`、邮件详情 `--reader: #222729`。
- 同步微调深色模式全局衍生背景与表面色阶（`--canvas`、`--surface`、`--surface-2`、`--surface-hover`、`--selected`、`--line`、`--line-strong`、`--mail-body`）、自适应邮件正文默认深色背景（`mailBody.ts`）以及 Electron 桌面端深色窗口背景色（`windowOptions.js`），使其与冷青灰三栏色阶协调一致。
- 缺失发件人与收件人信息统一留白：`displayName` 在发件人为空或未提供时返回空字符串 `""`（不再返回 `"未知"`）；阅读器 `MR07` 收件人在 `detail.to` 为空时直接留白（不再显示 `"未提供"`），并保持发件人/收件人行排版整洁。
- 优化阅读器正文未同步占位文案：将未归档/未同步完正文的默认空占位文案改为明确提示“邮件正文尚未完成同步”，移除“或内容为空”及“该邮件没有正文内容或内容为空。”等模糊描述。

### 非范围

- 不改变浅色模式（`html[data-theme="light"]`）的色值定义。
- 不改变显式固定浅色富文本邮件以独立白色纸张卡片承载的沙箱渲染策略。

### 验收标准

<!-- 规范（门禁必留，不得删除） -->

只写可观察、可独立验证的行为；每条使用稳定且不复用的 `AC-NNN`。需真实部署或人工环境验证时在编号前加 `[deploy]`。技术选型不作为行为 AC。

<!-- /规范 -->

- [ ] AC-001：深色模式下 `--sidebar` 为 `#1C1F21`、`--list` 为 `#212628`、`--reader` 与 `--mail-body`（含自适应深色邮件 iframe `body` 背景）为 `#222729`；`--canvas` 及桌面端深色 `windowBackgroundColor` 同步更新为比侧边栏更深的同色系冷底色，`--surface`、`--surface-2`、`--surface-hover`、`--selected`、`--line`、`--line-strong` 保持冷青灰阶梯且通过 CSS Token 门禁。
- [ ] AC-002：当邮件 `from` 为空、仅空白字符或未提供时，`displayName` 返回 `""`，邮件列表发件人（`ML09`）与阅读器发件人名称（`MR06`）及发件人地址行留白，不显示“未知”。
- [ ] AC-003：当邮件详情 `to` 为空或未提供时，阅读器收件人信息（`MR07`）值区域直接留白，不显示“未提供”。
- [ ] AC-004：当阅读器邮件正文尚未完成同步且未处于报错状态时，占位区域明确展示“邮件正文尚未完成同步”提示，不再出现“邮件正文尚未完成同步或内容为空”或“该邮件没有正文内容或内容为空。”文案。

### 可测试性声明

<!-- 规范（门禁必留，不得删除） -->

逐条说明不可自动测试的 AC 及替代验证；全部可测则写“全部 AC 可自动测试”。

<!-- /规范 -->

- 全部 AC 可自动测试。

## 上下文区

- 来源：`p029`、`p030`（2026-10-23 核实：`tokens.css:23-47`、`mailBody.ts:126`、`windowOptions.js:3-5`、`displayName.ts:4`、`MessageReader.tsx:175-185, 272-275` 均待按用户要求更新）

### 有意不测

- 无

### 测试策略

- 更新并运行 `src/frontend/src/design-system/darkTheme.test.ts`、`src/frontend/src/lib/mailBody.test.ts`、`src/desktop/windowOptions.test.js`、`scripts/check_css_tokens.mjs` 验证深色色阶与桌面背景色。
- 更新并运行 `src/frontend/src/lib/displayName.test.ts` 与 `src/frontend/src/components/MessageReader.test.tsx` 验证空发件人、空收件人留白及正文未同步提示文案。

### 未知契约清单

<!-- 规范（门禁必留，不得删除） -->

未核实的外部契约标为 `UNVERIFIED-BLOCKING` 或 `UNVERIFIED-SPIKE`；核实后改写为结论和验证方式。无则写“无”。

<!-- /规范 -->

- 无

### 风险与回退

- 风险：`mailBody.ts` 中 `parseColorBrightness` 预设暗色列表若未包含新阅读器底色 `#222729`，不影响常规 hex6 亮度计算，但需确保测试断言同步。
- 回退：同步更新关联单测与 `DESIGN.md` / `conventions.md` 色值引用。

### 依赖与约束

- 须遵守 `docs/blueprint/conventions.md` §一.2「邮件 HTML 渲染沙箱与主题边界」与 §一.3「前端语义颜色与 Token 纪律」。

### Finalization 时更新的 blueprint

- `docs/blueprint/conventions.md`：更新 §九.2 / §九.4 中关于阅读器空占位提示文案的描述。
