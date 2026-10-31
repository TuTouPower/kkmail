# Task review t068（reviewer_focus: 测试）

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

1. 测试可信与行为锚定：
   - 拒绝假绿：`smoke.spec.ts` 在真实浏览器中断言 `remoteImg.evaluate((el: HTMLImageElement) => el.naturalWidth) > 0`，确证图片真正完成网络获取与图像解码，同时挂载 console 监听确保零 CSP 拦截报错；
   - 后端集成测试 `tests/mail_core/test_remote_image_proxy.py` 驱动真实 PostgreSQL 库与 FastAPI Client，验证从未放行拦截（403）、放行后流式转发（200）、HEAD 请求响应头、Token 篡改（401）到撤销白名单后实时阻断（403）全状态生命周期。
2. 覆盖完整性与边界：
   - SSRF 过滤矩阵覆盖回环、私网、链路本地、云元数据、保留网段、IPv4-mapped 与 CIDR 白名单覆盖；
   - 验证了流式超过 10 MiB 断开连接、伪造 HTML/SVG 拒绝、重定向跳板防 SSRF 与重定向循环检测。
3. 危险模式扫描：
   - 零恒真断言、零静默跳过、零弱化断言；
   - 改测审查：
     - `mailBody.test.ts`：将失效的旧客户端直连测试替换为验证 t068 架构（CSP 永久锁定 `'self' data: cid:` 且外部 URL 重写为本站代理端点），测试注释中详细说明了理由，符合 TDD 规范；
     - `smoke.spec.ts`：增加真实浏览器位图解码断言（`naturalWidth > 0`）与零 CSP 报错检查，属于大幅强化验证；
     - `full_stack.spec.ts`：第 254 行移除了因 p062 废弃分组计数而失效的 `.tree-count` 断言，保留了更严格的分组成员展开与包含检查。

### AC 复验方式

- AC-001：`re_verified` — 查证 `mailBody.test.ts:70-85` 与 `smoke.spec.ts:205`，断言 iframe CSP 严格保持 `img-src 'self' data: cid:`。
- AC-002：`re_verified` — 重跑 `npm --prefix src/frontend run test:e2e`，通过 `smoke.spec.ts:180-213` 验证放行前后行为、真实位图解码（`naturalWidth > 0`）与控制台零 CSP 报错。
- AC-003：`re_verified` — 重跑 `scripts/run-mail-core-tests.sh run tests/mail_core/test_remote_image_proxy.py`，验证 `test_ssrf_ip_filtering_matrix` 与重定向跳板阻断用例。
- AC-004：`re_verified` — 查证并重跑 `test_fetch_safe_remote_image_size_limit`，流式读取超过 10 MiB 时成功抛出 `RemoteImageSizeLimitError`。
- AC-005：`re_verified` — 查证并重跑 `test_detect_safe_image_mime` 与 `test_fetch_safe_remote_image_fake_mime_rejected`。
- AC-006：`re_verified` — 查证并重跑 `test_remote_image_proxy_sender_allowlist_and_revocation`，撤销白名单后再次请求即刻返回 403。
- AC-007：`re_verified` — 查证 `mailBody.test.ts:85-98`，验证行内样式背景图经 `rewriteRemoteImages` 成功重写。
- AC-008：`re_verified` — 查证并重跑 `test_token_signing_and_tamper_proofing`，URL 篡改、Message ID 篡改及签名伪造均被拒。

coverage = 8 / 8 (100%)

verdict: PASS
