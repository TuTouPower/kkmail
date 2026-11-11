# Task review t005（reviewer_focus: 通用）

- task：`t005_sync_refresh_and_imap_id`
- spec：`docs/tasks/t005_sync_refresh_and_imap_id/spec.md`
- diff_anchor：`51947c44b01f95ed69799ce2de4cf13b924d95a3`
- target：`git -C '<local-path>' diff 51947c44b01f95ed69799ce2de4cf13b924d95a3`
- round: 1
- reviewed_at: 2026-10-22T11:25:00+08:00

reviewed_scope: ee17147f47a680d5

## Findings

Round 1 零 finding。

## 结论

- 前轮 finding 复核：首轮无前轮
- 本轮新发现：0 条
- 未进表的提示：无
- 总体判断：前端列表刷新按钮成功联动单账号或全局同步 API 并增加视觉反馈；应用层创建账号时同一事务自动排队初始同步任务；IMAP 客户端认证后发送 RFC 2971 ID 标识命令，解除网易等邮箱服务安全拦截，并在不支持环境下静默放行；全部测试覆盖且全部通过。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：`re_verified`，`src/frontend/src/components/MessageList.test.tsx` 独立测试在全局与单账号视图下点击刷新按钮，断言 `POST /api/accounts/sync-all` 与 `POST /api/accounts/{id}/sync` 正确触发，无异常。
- AC-002：`re_verified`，`tests/mail_core/test_imap_id_handshake.py::test_create_account_app_enqueues_initial_sync` 断言创建账号后 `worker_jobs` 表中必定存在对应 `SYNC_ACCOUNT_FOLDERS` 任务。
- AC-003：`re_verified`，`tests/mail_core/test_imap_id_handshake.py::test_imap_connect_sends_id_command` 断言连接认证后正确发送 RFC 2971 `ID` 客户端标识命令。
- AC-004：`re_verified`，`tests/mail_core/test_imap_id_handshake.py::test_imap_connect_tolerates_missing_id_support` 断言服务端返回不支持或错误时，连接正常建立且不阻断。

coverage = 4/4 = 100%

verdict: PASS
