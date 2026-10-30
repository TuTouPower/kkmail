---
tid: "t066"
slug: "remote_images_persist_and_reload"
title: "远程图片放行入库重载、内联图映射与单信深色覆盖修复"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
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

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

尚无 review 轮次。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：待执行时填写
- 测试：待执行时填写
- 黑盒：待执行时填写
- review：待执行时填写
- AC 证据：见 `handoff.json`

### 结果摘要

- 待执行时填写；遗留只写引用，不复制正文。
