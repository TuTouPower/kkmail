---
tid: "t016"
slug: "mail_protocol_integration"
title: "增强真实 IMAP 集成与邮件服务商协议契约测试"
status: "backlog"
branch: ""
worktree: ""
review_level: "full"
review_limit: "5"
verify_limit: "5"
diff_anchor: ""
depends_on: "t014"
conflicts_with: "t007,t012,t013,t014,t015,t017,t018,t019,t020,t021,t022,t023"
note: "本会话批准测试增强；本地复用专用 PG 容器、每轮独立测试库；仅创建 backlog"
---

# Task 过程总账

front matter 只经 `task.py` 修改；reviewer 只写对应 `review_*.md`。

## 实施笔记

执行期记录关键步骤、决策、验证、阻塞和用户批准的新轮次上限。

创建期不预测实施步骤。只记有追溯价值的内容；无事项时写“无”。

2026-10-22 核实已有 Dovecot Dockerfile、seed.eml、test_imap_provider_live.py、test_imap_sync_loop.py 和 test_gmail_graph_contracts.py；不新造第二套服务商适配器。

### 2026-10-22 主分支执行

- 用户明确要求直接在 main 分支按顺序执行 t013–t023，每完成一个 task 独立 commit。
- 在 `config/test_pg_compose.yaml` 中增加独立的 `imap` (Dovecot) 服务，消除对业务 Compose 环境变量与口令的依赖，绑定端口 `127.0.0.1:1143`；`scripts/start-mail-core-imap.sh` 优先利用测试 Compose 启动并等待服务健康就绪。
- 新增 `tests/mail_core/test_imap_protocol_suite.py`：
    - AC-001：就绪检查、密码错误拒绝、关闭端口连接失败断言；
    - AC-002：中文主题、multipart HTML/text 邮件正文同步；二进制附件 Blob 解密校验；同 Message-ID 重复邮件安全共存；再次同步保持严格幂等；
    - AC-003：远端增量变更（新增、Flag 变化、删除）在本地 reconcile 反映；本地标为已读经 `push_remote_operations` 写回到 Dovecot 并可在服务端 `\Seen` FLAGS 观测；
    - AC-004：移入 Trash 仅影响目标邮件；缺失 MOVE 能力拒绝不安全全目录 EXPUNGE；非 SSL 端口开启 `use_ssl=True` 立即握手失败阻断。
- 增强 `tests/mail_core/test_gmail_graph_contracts.py`：
    - AC-005：覆盖 Gmail/Graph 分页终止/重复 pageToken 终止、过期游标不前进、OAuth token 刷新失败与异常日志敏感凭据脱敏、5xx/Timeout 重试幂等性。
- 修复 `tests/mail_core/test_imap_sync_loop.py` 中测试账号针对本地 loopback 的 `MAIL_CORE_ALLOW_PRIVATE_HOSTS` 环境变量；`test_imap_provider_live.py` 与 `test_imap_sync_loop.py` 原来跳过的两项测试彻底激活并通过。
- 全量套件 361 passed / 0 skipped / 0 failed 彻底绿。

## Review 处置

每个结构化 finding 一行。`已修` 表示本 task 已修复；`遗留` 必须指向 `pNNN` 或 follow-up tid；`撤回` 必须写清理由。critical/important 未解决时不得 PASS。

- 已修：附件 Blob 正确通过 `MessageBlob.content_sha256` 经 `BlobStore.get` 进行流式解密校验；
- 已修：`push_remote_operations` 调用修正为接收 `account_id`，并断言 `pushed` 字段。
- 双人审查（code + test）结论均 PASS。

## 收尾报告

### 验收与验证

- spec：[`spec.md`](spec.md)
- 结果：全部行为 AC 验证通过，真实 IMAP 集成测试闭环。
- 测试：`scripts/run-mail-core-tests.sh run` 361 passed / 0 skipped；快速模式 255 passed / 102 skipped。
- 黑盒：真实 Dovecot 服务端 FLAGS、Message-ID、附件内容与删除收敛双向验证。
- review：`review_code.md` PASS，`review_test.md` PASS。
- AC 证据：`test_imap_protocol_suite.py`、`test_gmail_graph_contracts.py` 实测输出。

### 结果摘要

激活并增强了基于 Dovecot 容器的真实 IMAP 集成测试，覆盖中文多部分、加密附件解密校验、重复 Message-ID、本地写回与服务端可观察性、安全废纸篓移动与 TLS 阻断；完善了 Gmail/Graph 传输异常与敏感凭据脱敏断言，全量后端测试实现 0 跳过全通过。
