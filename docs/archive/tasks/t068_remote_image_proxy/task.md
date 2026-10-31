---
tid: "t068"
slug: "remote_image_proxy"
title: "外链图片服务端安全代理与防追踪防护"
status: "done"
branch: "t068_remote_image_proxy"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "49ec1f27a2e262158b4b1aab2ecf752dde87b506"
depends_on: ""
conflicts_with: ""
note: "基于 d003 确立的架构决策，建立服务端安全图片代理（Image Proxy）彻底消解 CSP 继承死锁；主站与正文 CSP 统一定格为 'self' data: 零外部出网，实现工业级防追踪与真实外链图片解码渲染"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 创建期事实与决策：
    1. 实测确证（`d003`）：Chromium 底层报 `violates directive: img-src 'self' data: blob:`；`about:srcdoc` 强制继承宿主 policy container，且 Electron 全 session 强制重写 CSP，客户端直连外链图片必然被阻断；
    2. 方案审阅结论：经 Claude Code (`opus 5.5`, effort=`high`) 深度架构审阅，独立正文 URL 端点方案存在 XFO 阻断、Electron 强制覆盖及双重净化 mXSS 等严重技术债，正式废弃并 drop t067；
    3. 采纳业界最佳实践：立项建立服务端安全图片代理（Image Proxy），主站、桌面端与正文沙箱统一永久锁定 `img-src 'self' data:` 零外部出网安全基线；
    4. 严格收敛 SSRF 防护、无状态 HMAC Token 签发、位图魔数校验、实时撤销与挂载真实 `_SPA_CSP` 的 Playwright 自动化验证。

- 实施期步骤与验证：
    1. 落地 `src/mail_core/security/remote_image_proxy.py`：实现严格 SSRF 过滤矩阵（含回环、私网、链路本地、云元数据、保留网段与 IPv4-mapped IPv6，支持白名单覆写），自定义 `SSRFSafeSyncBackend` 保持 TCP 直连安全 IP 并校验 TLS SNI，流式 10 MiB 上限检测，真实位图魔数核验（PNG/JPEG/GIF/WebP），无状态 HMAC Token 签名；
    2. 落地 `/api/mail/messages/{id}/remote-images` 代理路由与详情接口外链 URL 扫描重写映射，实时核验数据库放行状态；
    3. 前端 `mailBody.ts` 实现 `rewriteRemoteImages`，统一将宿主、桌面端与沙箱 iframe 的 CSP 策略定格为 `'self' data: cid:`，守住零外部出网安全基线；
    4. 单元与集成测试：SSRF 矩阵、魔数、超时超限、Token 验签与实时撤销阻断测试全绿；
    5. 全栈黑盒验证：Playwright 端到端冒烟与真实全栈测试全部 PASS，确证外链图片经代理流式加载后在真实 Chromium 中成功解码（`naturalWidth > 0`），控制台零 CSP 报错。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

### Round 1 (2026-10-31T14:45:00+08:00)

Round 1 零 finding。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部满足
- 测试：`pytest .repo_template/tests -q -m contract` (189 passed)、`scripts/run-mail-core-tests.sh run tests/mail_core/test_remote_image_proxy.py` (23 passed)、`(cd src/frontend && npm test && npx tsc -b && npm run build)` (53 files / 571 passed)、`npm --prefix src/desktop test` (all passed) 全部通过
- 黑盒：`npm --prefix src/frontend run test:e2e` (20 passed) 与 `python3 scripts/run_full_stack_e2e.py` (8 passed) 全部通过
- review：Round 1 code_review (PASS) + test_review (PASS) 零 finding
- AC 证据：见 `handoff.json`

### 结果摘要

- 采纳业界现代 Webmail 标准架构，以服务端安全图片代理（Image Proxy）彻底消解沙箱 iframe 继承宿主 CSP 导致的外部图片死锁；
- 全站主应用外壳、桌面端及邮件正文沙箱的 CSP 统一永久定格为 `'self' data:`，杜绝任何浏览器直接出网，实现工业级防追踪与无感解码渲染。
