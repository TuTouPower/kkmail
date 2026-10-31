# Task review t069（reviewer_focus: 代码）

- task：`t069_remote_image_extract_and_fetch_robustness`
- spec：`docs/tasks/t069_remote_image_extract_and_fetch_robustness/spec.md`
- diff_anchor：`7cbeb45e060ced1b683fe21664ed7c03ad801e1d`
- target：`git -C '$WORKTREE' diff 7cbeb45e060ced1b683fe21664ed7c03ad801e1d`
- round：1
- reviewed_at：2026-10-31T17:25:00+08:00
reviewed_scope: 6cf3ca1a9281fec0

## Round 1 (2026-10-31T17:25:00+08:00)

### Findings

Round 1 零 finding。

### 维度核验

1. 规格合规：
   - 提取改为 `html.parser`（`convert_charrefs=True`），无引号/单双引号/大小写/实体/协议相对全部覆盖，且 `handle_starttag` 对所有元素检查 `style`，背景图不再局限于 `<img>`；与 AC-001/002/003/004 对应。
   - `normalize_remote_image_url` 统一 trim、`//`→`https:`、长度校验；前端 `normalizeRemoteImageUrl` 采用同一语义，避免实体/协议相对导致的 key 不匹配。
   - 错误分类完整：DNS/连接/TLS/上游非 2xx → 502，超时 → 504，非法目标 400，Token 401，未放行 403，消息 404，超限 413，格式 415；异常文案改为固定字符串，不再回显内部 IP 或目标 URL 细节（AC-005）。
   - `_connect_with_fallback` IPv4 优先逐个尝试，全部超时 504、全部不可达 502（AC-006）。
   - SVG 放行前 `validate_svg_payload` 拒绝 `<script`、事件处理器、`foreignObject`/`iframe`/`embed`/`object`、外部 `href|src`，并限制 64 KiB；响应头仍保留 `nosniff` 与 `Content-Security-Policy: default-src 'none'`（AC-007）。
   - 既有 SSRF/IP 过滤、大小上限、Token 签名与撤销逻辑未改（AC-008）。
2. 代码质量：
   - 提取器职责单一，`_add` 承担去重/上限，`_done` 提前终止收集；无死代码（额外加过的 `_BaseURLParser` 已删除）。
   - 异常层次清晰：`RemoteImageTimeoutError(TimeoutError)` 与 `RemoteImageFetchError(RuntimeError)` 分离，API 层一一映射。
   - 资源释放：SVG 分支在 `finally` 关闭连接，位图流在 `finally` 关闭连接；超时/异常路径均关闭。
   - 文件体积：`remote_image_proxy.py` 约 560 行（实现源码 ≥400 提示阈值，本 task 净增约 240 行）；`mail.py` 已超 800 行且本 task 净增约 10 行——均为既有大文件的小幅必要改动，无重复逻辑导致的行为分叉，结论段提示不阻断。
   - 圈复杂度：`fetch_safe_remote_image` 分支较多（CC ≥ 10），结论段提示后续可继续拆分为 `_open_connection` / `_classify_response`，不阻断。
3. 安全：
   - SVG 放行是最敏感变更：`<img>` 上下文不执行脚本；直接打开代理 URL 时依赖 `default-src 'none'` CSP 与危险模式拒绝双重防护；外部引用正则覆盖 `xlink:href`（有测试）。
   - 多 IP 回退仍只连接经 `is_safe_ip` 校验的地址，不引入 DNS Rebinding 窗口。
   - 错误响应不泄露内部信息。

### AC 复验方式

- AC-001：`re_verified` — 生产 Google 原文离线提取由 0 变为 6；E2E 新用例断言无引号图片 `naturalWidth > 0`。
- AC-002：`re_verified` — `test_extract_decodes_html_entities_like_dom` 与 `mailBody.test.ts` 实体用例；E2E 覆盖实体图片代理解码。
- AC-003：`re_verified` — `test_extract_normalizes_protocol_relative_urls`、前端协议相对用例、E2E 断言背景图已重写。
- AC-004：`re_verified` — 背景图在任意元素 `style` 中提取（含无引号/实体/协议相对），前端重写用例覆盖。
- AC-005：`re_verified` — API 集成测试断言 504/502/415 与响应体不含内部信息；`mail.py` 文案为固定字符串。
- AC-006：`re_verified` — `test_connect_falls_back_across_safe_ips_ipv4_first`、超时/全不可达分类测试。
- AC-007：`re_verified` — `test_detect_svg_mime`、`test_validate_svg_payload_accepts_static_svg`、7 类危险 SVG 参数化拒绝、超限拒绝。
- AC-008：`re_verified` — 既有 SSRF 矩阵、大小上限、Token、撤销测试全部保留并通过（39 项代理集成）。
- AC-009：`re_verified` — E2E 新夹具邮件（无引号 + 实体 + 协议相对）真实 CSP 下 3 张 `<img>` 全部 `naturalWidth > 0` 且零 CSP 违规。

coverage = 9 / 9 (100%)

verdict: PASS
