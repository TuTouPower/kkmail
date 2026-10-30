---
tid: "t066"
slug: "remote_images_persist_and_reload"
title: "远程图片放行入库重载、内联图映射与单信深色覆盖修复"
status: "done"
branch: "t066_remote_images_persist_and_reload"
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: "b3ac8b962eeba3b86ff7397818d770720aa64443"
depends_on: ""
conflicts_with: ""
note: "来源 p066、p067、p068；单邮件与发件人放行持久化入库、正文强制重建、cid 内联图映射及阅读器单信深色覆盖多信隔离"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

- 创建期审查：Codex `gpt-6.1-sol` 审阅结论 `CHANGES_REQUIRED`。
- 规范修订：已针对 8 项重点意见及术语边界完成 spec 深度加固：
    01. I-01：规定在无网络副作用离线 DOM 容器中提取与注入，仅以属性 API 修改受控图片 MIME 的 data URL，统一由 DOMPurify 清洗输出，杜绝父页面网络副作用与 XSS；
    02. I-02：制定正文内联图片专用资源配额（单张正文内联图片 ≤10 MiB、单邮件累计正文内联图片 ≤20 MiB、最多 3 并发、5s 超时），超限/异常局部降级为正文占位（附件列表仍保留手动下载），普通文件附件绝不自动下载；切信即时 abort；
    03. I-03：设置页撤销发件人白名单即时作废在途详情请求，未获权威结果前阻断渲染旧放行正文；CID 注入绑定邮件 UUID 与请求版本防串写；
    04. I-04：服务端作为发件人白名单唯一权威，基于结构化 `from_address` 规范化与校验，建立数据库唯一索引并保障并发幂等；
    05. I-05：远程图片识别范围覆盖协议相对路径 `//`；样式背景图由 CSP 严格阻断；
    06. I-06：分离 URL 单次百分号解码与报头去首尾括号，异常/碰撞安全降级；
    07. I-07：`viewModeOverride` 提升至应用级内存 store（`mailStore`），跨阅读器挂载（切信、设置页往返）保留，刷新页面重置；
    08. I-08：测试矩阵补齐 Chromium + WebKit 双浏览器及真实 PostgreSQL / Cookie 全栈 E2E 验证；
    09. 明确承接 `p067` 与 `p068`，纠正原历史 pending 中“不扩大范围”的早期排他记录；
    10. 术语与边界消除歧义：严格区分普通文件附件（必须用户显式点击才下载，绝不自动静默拉取）与正文内联图片附件（打开邮件渲染正文时按需获取），明确配额限制仅针对正文内联图片转 Base64 注入，绝不作用于普通文件附件。
- 开源邮件客户端实现调研（Cypht, Zero, SnappyMail, Thunderbird, Mailspring）：
    1. Thunderbird：基于 Gecko 原生内核，底层注册 `cid:` / `mailbox:` / `imap:` 协议处理器，直接按 Content-ID 在 MIME 树解析数据流，无需 HTTP Cookie 鉴权；
    2. Mailspring：基于 Electron + React，利用桌面主进程注册 `mailspring://` 私有协议或读本地缓存文件，绕开 Web 跨域 Cookie；
    3. SnappyMail：基于 Web 架构（PHP+JS），将 `cid:` 重写为带有时效性签名 Token 的只读 URL（`?_action=inline&_id=...&_token=...`），沙箱 iframe 无 Cookie 亦可通过 Token 鉴权直接流式拉取；
    4. Zero (Mail-0)：基于 Next.js + React，邮件解析阶段直接将附件转为 Base64 `data:` URL 替换 `cid:` 节点；
    5. Cypht：轻量 Webmail，因缺少完善的 CID 映射流水线，近期（2026-10-29）在 Issue #2134 中复现了内联图碎图缺陷。
- 方案决策（采纳方案 B：Signed URL 预览）：
    - 经 Codex 深度评估与用户确认，正式采纳方案 B（短期无状态 HMAC 签名 Token 链接）：
        1. 独立预览端点：`/api/mail/attachments/{id}/preview` 仅凭有效 Token 放行，不依赖也不回退到 Cookie 认证；常规附件下载接口保持 Cookie 认证不变；
        2. 签名规范：确定性序列化绑定 `version`、`purpose=inline-image-preview`、`attachment_id`、`issued_at`、`expires_at`（15分钟），HMAC-SHA256 恒定时间比对；
        3. 安全位图白名单：仅限 PNG、JPEG、GIF、WebP 4 种安全位图，明确排除 SVG；按文件头魔数校验真实二进制；强制附带 `X-Content-Type-Options: nosniff`；
        4. 精准 CSP 限制：未放行远程图片时，正文 CSP 仅精准允许自身预览 API 路径及 `data:`，不放开全局 `http(s):`；
        5. 凭据脱敏：带 Token 的正文不入库持久化；服务端日志、APM 与前端错误上报对 `token` 参数自动脱敏；
        6. 取消前端 Base64 内存配额与异步拉取管道，浏览器原生流式拉取图片；保留后端流式传输超时与单信签发上限防滥用保护。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

| finding_id | status | 说明 |
|---|---|---|
| t066_code_f001 | 已修 | 正文 CSP 恢复为精准端点路径 `img-src /api/mail/attachments/ data:;`，放行时为 `img-src https: http: data: /api/mail/attachments/;` |
| t066_code_f002 | 已修 | `_SPA_CSP` 恢复为 `img-src 'self' data: blob:;` 守住主应用安全基线 |
| t066_code_f003 | 已修 | `MessageReader.tsx` 引入 `allowImagesAbortRef`，切信即时 abort 在途放行请求并清空状态 |
| t066_code_f004 | 已修 | `SettingsModal.tsx` 移除发件人时先 `cancelQueries` 再 `removeQueries` 阻断旧在途请求回写 |
| t066_code_f005 | 已修 | `normalizeHeaderContentId` 移除二次解码，`rewriteCidImages` 显式过滤 `is_inline !== false` |
| t066_code_f006 | 已修 | `api_preview_inline_attachment` 支持 GET 和 HEAD 方法 |
| t066_code_f007 | 已修 | `mailCore.ts` 路径参数统一使用 `encodeURIComponent` |
| t066_test_f001 | 已修 | 测试断言严格对齐 spec 规定的 CSP 规则 |
| t066_test_f002 | 已修 | 补齐预览端点 200 成功响应、流式返回、HEAD 请求、403 安全拦截与日志脱敏测试 |
| t066_test_f003 | 已修 | 补齐设置页白名单移除与详情查询清理及重开恢复拦截测试 |
| t066_test_f004 | 已修 | 补齐放行在途保护、失败重试及非法发件人隐藏放行按钮测试 |
| t066_test_f005 | 已修 | 补齐报头原样保留、超长/非法编码安全降级单测 |
| t066_test_f006 | 已修 | 补齐删除级联保留发件人、跨账号生效及 404/401 边界测试 |
| t066_test_f007 | 已修 | 补齐 viewModeOverrides 不进 localStorage 持久化断言 |

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：通过。18 条行为 AC 全部实现且自动化验证闭环，覆盖远程图片单封/发件人持久化放行、iframe 强制销毁重建、CID 内联图片 HMAC Signed URL 原生流式预览、安全位图白名单（排除 SVG）、沙箱安全隔离与单信深色覆盖内存字典管理。
- 测试：全量前端测试 53 文件 571 用例 passed、后端相关测试全部 passed、OpenAPI 一致性检查与 CSS token 检查通过。
- 黑盒：Playwright E2E（含 Chromium 真实端到端冒烟 20 用例全部 passed，含 `t066` 专项测试）。
- review：Round 2 full review 双路 PASS（`review_code.md` 与 `review_test.md` 均 PASS，14 条 findings 全部闭环处置为已修）。
- AC 证据：见 `handoff.json`

### 结果摘要

- 来源 p066、p067、p068 全部在本 task 实施并闭环，无遗留。实现单邮件与发件人白名单服务端持久化、iframe 强制重新挂载、内联图片短期无状态 HMAC 签名 Token 链接（Signed URL）免 Cookie 安全流式拉取、设置页白名单管理与单信深色覆盖内存字典生命周期。
