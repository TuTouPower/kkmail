---
tid: "t069"
slug: "remote_image_extract_and_fetch_robustness"
title: "远程图片提取与代理容错修复"
status: "done"
branch: "t069_remote_image_extract_and_fetch_robustness"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "7cbeb45e060ced1b683fe21664ed7c03ad801e1d"
depends_on: ""
conflicts_with: ""
note: "来源 p069；修复无引号 src/实体/协议相对漏提取，统一服务端 HTML5 解析语义，区分 DNS/网络/上游/安全错误码，SVG 安全放行与多 IP 回退"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 创建期事实与量化（来源 `p069`）：
    1. L1 全库扫描 19897 封有正文 / 18389 封含 `<img>`：558 封提取为 0（全碎）、2519 封部分漏提取、2874 封 HTML 实体不一致、2 封仅协议相对；
    2. L2 真实试拉 800 URL：556 成功；DNS 失效被误报 SSRF 拦截 22、上游 4xx/409 与超时混同 502、合法 SVG 被 415 拒 16；
    3. L3 生产 CSP + 生产代理端点 + 真实 Chromium：Google 原邮件两张图 `naturalWidth` 160/512，零 CSP 违规，确证代理链路完好、缺陷仅在提取。
- 待实施验证的修复面：F1 无引号、F2 实体、F3 协议相对、F4 错误分类、F5 多 IP 回退、F6 SVG 安全放行。
- 实施决策与证据：
    1. 提取改为标准库 `html.parser`（`convert_charrefs=True`），自动覆盖无引号、单双引号、实体解码与大小写；`normalize_remote_image_url` 统一补全协议相对并校验长度；`handle_starttag` 对任意元素检查 `style` 中的 `url(...)`，因此背景图不再局限于 `<img>`；
    2. 生产 Google 原邮件离线验证：修复前提取 `0`，修复后提取 `6` 个唯一 URL（正文 9 个 `<img>` 去重）；
    3. 前端新增 `normalizeRemoteImageUrl`，映射 key 与 DOM 取值使用同一规范化语义；
    4. 错误分类：DNS/连接/TLS/上游非 2xx → 502，连接或读取超时 → 504，其余保持 400/401/403/404/413/415；响应体改为固定文案，不再拼接异常字符串（原先会回显内部 IP）；
    5. 多 IP 回退：`_connect_with_fallback` 按 IPv4 优先逐个尝试，全部超时 → 504，全部不可达 → 502；通过注入 connector 单测覆盖顺序与分类；
    6. SVG：`detect_safe_image_mime` 识别 `image/svg+xml`，`validate_svg_payload` 拒绝脚本、事件处理器、`foreignObject`/`iframe`/`embed`/`object`、外部 `href`/`src`，并限制 64 KiB；保留 `nosniff` 与 `default-src 'none'` 响应头。
- 验证：后端单测 28 passed；代理相关 PG 集成 39 passed；前端 25 passed（mailBody）+ 全量 571 passed；Playwright E2E 21 passed（新增 t069 用例真实解码无引号/实体/协议相对图片）；全栈 E2E 8 passed；契约 189 passed。
- 基线既存失败（与本 task 无关，main 上同样复现）：`test_microsoft_oauth.py::test_device_concurrent_poll_and_save_use_same_identity_guards_pg`（并发 poll 触发 429）；前端 `npm run lint` 的 `Sidebar.tsx` exhaustive-deps 5 项。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-31T17:20:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：契约 189 passed；后端单测 28 passed；代理 PG 集成 39 passed；前端 `npm test` 53 files / 571 passed；`tsc -b` 与生产构建通过；桌面单测于 t068 基线通过（本 task 未触达桌面代码）；基线既存失败见实施笔记
- 黑盒：`npm --prefix src/frontend run test:e2e` 21 passed；`python3 scripts/run_full_stack_e2e.py` 8 passed
- review：Round 1 code PASS + test PASS 零 finding
- AC 证据：见 `handoff.json`

### 结果摘要

- 修复生产碎图根因：服务端改用 HTML5 属性解析语义提取正文图片 URL，覆盖无引号、实体、协议相对与背景图，与前端 DOM 取值一致；
- 代理容错增强：错误类别可区分且不泄露内部信息、多 IP IPv4 优先回退、合法 SVG 静态安全扫描后放行；
- 来源 pending `p069` 已归档，闭环于本 task。
