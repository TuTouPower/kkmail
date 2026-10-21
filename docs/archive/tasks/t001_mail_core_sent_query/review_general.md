# Task t001 Review: General

## Round 1

reviewed_scope: 98839d0b2bc76709

### 审查结论

verdict: PASS

### 检查项核验

1. **AC 覆盖**：
   - AC-001：`/api/mail/inbox?folder_role=sent` 支持按角色查询已发邮件，支持 keyset 分页与 `account_id` 过滤。
   - AC-002：未传 `folder_role` 时默认返回 `role="inbox"`，向后兼容。
   - AC-003：IMAP Provider 映射中包含 `"已发送"`、`"已发送邮件"` 与 `\Sent` 标志解析为 `role="sent"`。
2. **测试与质量**：
   - 新增 `tests/mail_core/test_folder_role_inbox_api.py` 覆盖多账号 role 查询与联合过滤。
   - 扩展 `tests/mail_core/test_imap_remote_id.py` 覆盖 IMAP 角色映射。
   - 全量门禁（contract 测试、前端构建与类型检查、桌面端测试、E2E 冒烟测试）全部通过。
3. **架构与 Schema**：
   - 更新 `schemas/openapi.json` 与前端生成的 `schema.ts`，检查无 drift。
   - 更新 `docs/blueprint/architecture.md`、`docs/specs/mail_sync_and_storage.md` 与 `docs/specs_index.md`。
