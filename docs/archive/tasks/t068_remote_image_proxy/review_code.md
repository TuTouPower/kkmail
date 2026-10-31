# Task review t068（reviewer_focus: 代码）

- task：`t068_remote_image_proxy`
- spec：`docs/tasks/t068_remote_image_proxy/spec.md`
- diff_anchor：`49ec1f27a2e262158b4b1aab2ecf752dde87b506`
- target：`git -C '$WORKTREE' diff 49ec1f27a2e262158b4b1aab2ecf752dde87b506`
- round：1
- reviewed_at：2026-10-31T14:45:00+08:00
reviewed_scope: b8a6facb5a811fca

## Round 1 (2026-10-31T14:45:00+08:00)

### Findings

Round 1 零 finding。

### 维度核验

1. 规格合规与不变量：
   - 守护了主应用外壳与邮件沙箱的 `'self' data: cid:` 零外部出网安全基线（AC-001）；
   - 代理端点（`GET/HEAD /api/mail/messages/{id}/remote-images`）提供无状态 HMAC Token 校验，实时验证数据库放行状态（AC-002, AC-006, AC-008）；
   - 多层 SSRF 防护门禁全面覆盖私网、回环、链路本地、云元数据、CGNAT、保留段与 IPv4-mapped IPv6，直连安全 IP 且保护 TLS SNI 防御 DNS Rebinding（AC-003）；
   - 流式 10 MiB 上限检测与 5s/15s 超时控制（AC-004）；
   - 真实位图魔数核验排除了 SVG、HTML、JS 及可执行格式（AC-005）；
   - 前端安全重写正文中 `img[src]` 与行内背景图（AC-007）。
2. 代码质量与复杂度：
   - 职责分明：网络安全传输层（`remote_image_proxy.py`）、路由层（`api/mail.py`）、数据转换层（`mailCore.ts`）、DOM 清洗重写层（`mailBody.ts`）与渲染层（`MessageReader.tsx`）各司其职；
   - 错误处理严格，异常均映射为对应 HTTP 状态码（400/401/403/404/413/415/502）；
   - 文件物理行数：`src/mail_core/security/remote_image_proxy.py` 435 行（未超 800 行阈值）；函数圈复杂度未超标；
   - 排除项：`schemas/openapi.json` 与 `src/frontend/src/api/generated/schema.ts` 为代码生成契约文件，按规则排除。

### AC 复验方式

- AC-001：`re_verified` — 查证 `src/frontend/src/lib/mailBody.ts:365`，正文沙箱 CSP 严格锁定为 `default-src 'none'; img-src 'self' data: cid:; style-src 'unsafe-inline'; font-src data:`；`src/mail_core/api/app.py:123` 保持 `img-src 'self' data: blob:`。
- AC-002：`re_verified` — 查证 `MessageReader.tsx` 与 `smoke.spec.ts` 真实浏览器端到端测试，放行后经代理端点流式加载且解码成功（`naturalWidth > 0`），控制台无 CSP 报错。
- AC-003：`re_verified` — 查证 `src/mail_core/security/remote_image_proxy.py:87-214` 的 SSRF 矩阵过滤逻辑与 `SSRFSafeSyncBackend` 重新解析连接。
- AC-004：`re_verified` — 查证 `remote_image_proxy.py:377-399` 流式迭代器在超过 `MAX_IMAGE_BYTES`（10 MiB）时立即关闭上游连接并抛出 `RemoteImageSizeLimitError`。
- AC-005：`re_verified` — 查证 `remote_image_proxy.py:228-254` 魔数检测逻辑，仅返回 `image/png`, `image/jpeg`, `image/gif`, `image/webp`，严格拒绝 SVG 和非位图。
- AC-006：`re_verified` — 查证 `api/mail.py:1003-1008` 每次请求实时调用 `is_remote_images_allowed(session, msg_uuid, msg.from_address)`，撤销后立即返回 403。
- AC-007：`re_verified` — 查证 `mailBody.ts:194-214` 正则匹配并重写 `background-image: url(...)` 外部链接。
- AC-008：`re_verified` — 查证 `remote_image_proxy.py:264-297` 的 HMAC 验签逻辑与 `redact.py:38` 的 URL/Token 日志脱敏规则。

coverage = 8 / 8 (100%)

verdict: PASS
