# 017 邮件文档渲染契约：srcdoc 注入视口与固定宽度收敛 (t081)（2026-11-20）

- **背景**：p081（2026-11-20 用户截图）显示同一封 Cloudflare 周报在 Gmail 中完整适配手机屏宽，在 kkmail 中标题、账号链接与统计表格右侧被截断。iframe/srcdoc 的技术选型由零外部出网与 CSP/sandbox 隔离驱动（`docs/blueprint/architecture.md`「服务端安全图片代理与零外部出网架构」、A384），但「独立文档如何适配视口」从未进入渲染契约。`buildMailSrcdoc()` 构造 head 时只注入 CSP、base、配色和 `img{max-width:100%}`，没有 viewport meta 与表格/容器宽度约束；srcdoc 是独立浏览上下文，宿主 `index.html` 的 viewport meta 不会继承。E2E 在 360px 视口用固定宽度表格邮件复现：`html.scrollWidth=680`、`clientWidth=309`。
- **决策**：把「邮件文档渲染契约」固定在唯一文档构造点 `src/frontend/src/lib/mailBody.ts` 的 `buildMailSrcdoc()`：head 必须注入 `<meta name="viewport" content="width=device-width, initial-scale=1">`；style 必须包含对 `div,table,td,th` 的 `width:auto !important; max-width:100% !important; height:auto` 宽度收敛，以及 `html,body{max-width:100%}`；原有 `img{max-width:100%;height:auto}` 保留。所有 HTML 正文（含深色反相分支）共用该契约。
- **原因与选型**：
    - viewport meta 必须放在 srcdoc 自身：它只定义布局视口，挡不住邮件内联 `width="680"` / `style="width:680px"` 的固定宽度表格，单独注入不够。
    - CSS 宽度收敛是本次采用的基线：把固定宽度重写为「自动 + 不超过容器」，保证内容进入屏内而非依赖横向滚动。实测发现仅 `max-width:100% !important` 被 Chromium 的表格布局忽略（table 计算宽度仍为 680px），因此必须同时以 `width:auto !important` 覆盖写死宽度；该做法代价是复杂表格的列宽由浏览器重新分配，可能偏离原版式，但保证信息完整可读。
    - 按实测 `scrollWidth` 做 transform scale-to-fit 作为**条件性兜底**：本次样本在宽度收敛后已无溢出，故未启用；若后续样本仍溢出，应作为独立增强并设最小可读缩放比，而不是默认缩小全部邮件。
    - 在清洗阶段把固定宽度重写为百分比（Gmail 式）保真度最高但复杂度和回归面最大，列为长期演进，不在本 task 实施。
- **安全边界（不变量）**：CSP 仍为 `default-src 'none'; img-src 'self' data: cid:; style-src 'unsafe-inline'; font-src data:`；sandbox 标志、`no-referrer`、`<base target="_blank" rel="noopener noreferrer">` 与远程图片代理重写逻辑不变；适配只发生在 srcdoc 的 head/style 层，不放宽任何隔离约束，也不引入外部资源。
- **影响与验证**：单测断言 srcdoc 含 viewport 与宽度约束且 CSP 不回归；E2E 复用 t080 的共享 360px 视口模板（`tests/e2e/layoutGeometry.ts`），用固定宽度表格 fixture 断言 iframe 内 `html`/`body` 的 `scrollWidth <= clientWidth + 1`。`docs/blueprint/testing.md` 的 blackbox_verify 纳入该用例。
- **回退**：移除 `buildMailSrcdoc()` 的 viewport meta 与 `widthStyle` 宽度规则、保留其余 head/CSP 内容即可回到修复前行为；无数据迁移、无后端/部署变更。
