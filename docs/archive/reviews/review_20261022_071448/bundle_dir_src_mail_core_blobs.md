# Bundle Review — dir:src/mail_core/blobs

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 8 allowlisted tracked files

## Findings

- [Medium][99] src/mail_core/blobs/archive.py:260-L327 — 额度暂停归档没有生产恢复调用，释放空间后任务永久停住 — 证据：resume_quota_paused_archives() 只有测试调用；运行时超限会把剩余邮件设为 ARCHIVE_PAUSED_QUOTA，claim batch 不再领取该状态。 — 依据：ARCHIVE_PAUSED_QUOTA 状态机允许恢复，但生产路径不存在。 — 修复：容量恢复后由受控周期任务重置并重新排队暂停归档。
- [Medium][100] src/mail_core/blobs/archive.py:556-L567 — 同名且无 Content-ID 的不同附件被当成重复项静默丢弃 — 证据：附件去重键为 (filename, content_id)；同一邮件含两个 filename 相同、CID 为空的 MIME part 时，第二个被跳过。 — 依据：docs/specs/mail_sync_and_storage.md:27 要求解析生成全部 Attachment。 — 修复：按 MIME part 身份或序号区分附件；重放保护不得合并不同 part。
- [Medium][98] src/mail_core/blobs/archive.py:529-L548 — 正文归档入库后未刷新全文搜索索引 — 证据：metadata 阶段先调用 upsert_message_search，此时 body 尚未归档；本处写入 MessageBody 后没有再次更新索引，全文搜索长期只有 snippet。 — 依据：src/mail_core/search/index.py:23-35；docs/specs/inbox_ui_and_search.md:14 与 AC-005。 — 修复：归档事务写 body 后同事务 upsert search row，并增加归档到搜索的行为覆盖。
- [High][96] src/mail_core/blobs/gc.py:149-L181 — GC 的二次引用查询与 unlink 之间存在竞态，会删除刚重新引用的 blob — 证据：GC 查询 digest 的 live_refs 为 0 后直接 unlink；归档可在查询后提交同 digest 的 MessageBlob/link，unlink 后 DB 留下指向缺失文件的行。 — 依据：src/mail_core/blobs/archive.py:464-466,507-527；docs/specs/mail_sync_and_storage.md:28 要求 race-safe 二次校验。 — 修复：按 digest 串行化引用创建与 unlink，或采用 tombstone/引用核验协议。
- [Medium][93] src/mail_core/blobs/archive.py:464-L527 — 删除邮件与归档写入并发会留下不受 GC 管理的加密孤儿文件 — 证据：archive 先把 blob 写到文件系统；若此时 trash/delete 级联移除 archive state，随后代码跳过 DB MessageBlob/link 创建。GC 只枚举 DB MessageBlob，故文件不会被回收。 — 依据：src/mail_core/blobs/gc.py:52,92 仅处理有数据库记录的 blob。 — 修复：状态重查失败时按 digest 安全核验清理，或增加与 GC race-safe 的孤儿文件对账器。
- [Medium][90] src/mail_core/blobs/archive.py:362-L468 — 硬配额会被单封大邮件或并发归档超出 — 证据：容量仅在归档前检查；完整 MIME/附件写完才增加统计，无跨 worker 预留，且以明文字节计数而磁盘保存 AEAD framing ciphertext。 — 依据：MAIL_CORE_BLOB_HARD_BYTES 的名称与 hard quota 行为不符。 — 修复：基于最终 ciphertext 字节跨 worker 预留容量，并在提交前处理将超限对象。

## Files examined

- src/mail_core/blobs/__init__.py
- src/mail_core/blobs/access.py
- src/mail_core/blobs/archive.py
- src/mail_core/blobs/crypto.py
- src/mail_core/blobs/gc.py
- src/mail_core/blobs/quota.py
- src/mail_core/blobs/rotate.py
- src/mail_core/blobs/store.py
