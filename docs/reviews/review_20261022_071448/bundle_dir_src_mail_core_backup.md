# Bundle Review — dir:src/mail_core/backup

- Target: kkmail @ f915e78bcfc81767386f86b5e9f2448235f44fa7
- Coverage: 3 allowlisted tracked files

## Findings

- [Medium][100] src/mail_core/backup/crypto.py:80-L105 — 密封备份加解密一次性读入整个文件并占用 O(n) 内存 — 证据：加密与解密分别调用 read_bytes()/f.read() 后一次性 AESGCM；数据库与 blob 打包 tar 可很大，处理峰值内存接近整个备份大小。 — 依据：src/mail_core/backup/package.py:295-303 先生成完整 tar；流式备份契约与 blobs/crypto.py 的分块实现不一致。 — 修复：改用带认证的分块 frame，并检测截断与重排。
- [Medium][96] src/mail_core/backup/package.py:276-L548 — 备份明文 staging 目录权限宽且异常终止会留下明文数据 — 证据：默认 staging 位于共享临时父目录，写入明文 DB dump、blob tar 和恢复树；依赖默认 umask，SIGKILL/断电不会执行 finally 清理。 — 依据：docs/guides/security.md:74-78 要求密封备份并保护明文数据。 — 修复：在受控私有目录创建 0700 stage、文件设为 0600，清理 stale stage；尽可能流式校验以减少持久明文树。

## Files examined

- src/mail_core/backup/__init__.py
- src/mail_core/backup/crypto.py
- src/mail_core/backup/package.py
