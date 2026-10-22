# p020 MIME归档报头回填与附件文件名裸GBK解码漏洞及脏数据报错契约

- 现象：t007 仅覆盖了 IMAP 元数据拉取解析，`src/mail_core/blobs/archive.py` 在正文归档时仍使用 `email.policy.default` 解析 MIME。当邮件报头或附件文件名包含裸 GBK 字节时，报头回填和附件文件名（`part.get_filename()`）依然会被损坏为带 `\ufffd` 的乱码（如 `ĵ.pdf`）；且遇到真实损坏数据时缺乏显式报错与校验。
- 影响：
    1. 正文归档阶段若触发报头元数据回填，遇到裸 GBK 字节时会直接向数据库写入包含 `\ufffd` 的二次损坏字符串；
    2. 携带裸 GBK 编码文件名的邮件附件，文件名被损坏截断；
    3. 异常数据未快速失败（fail-fast），可能静默流入存储。
- 根因：
    1. **MIME 报头回填误用 `default_policy`（产品缺陷）**：`src/mail_core/blobs/archive.py:688-697` 使用 `email.message_from_bytes(mime, policy=default_policy)` 与原生 `str(...)`，`default_policy` 对未声明编码的 8-bit 直接替换为 `\ufffd`，未复用确定性编码回退解析逻辑；
    2. **附件文件名编码提取缺陷（产品缺陷）**：`src/mail_core/blobs/archive.py:71` 的 `parse_mime_content` 同样受 `default_policy` 影响，对裸 GBK 附件名生成替换符乱码；
    3. **架构约束（用户明确指令）**：禁止在生产代码中编写任何暗藏的「历史数据隐式自愈」逻辑；历史脏数据由人工/显式脚本运维修复（本次已手动修复生产库 14 封历史邮件）。运行时代码若检测到真实不可恢复脏数据或格式破损，必须显式报错/记录失败，严禁静默吞掉或推测自愈。
- 测试缺口：
    1. 缺少 `archive.py` 元数据回填路径遇到裸 GBK 报头的回归测试；
    2. 缺少 `parse_mime_content` 对裸 GBK 附件文件名正确解码的断言测试；
    3. 缺少遇到不可恢复损坏数据时显式报错/记录结构化失败的契约测试。
- 线索：
    1. 报头回填与 policy 复现：`.scratch/repro_header_mojibake_gap.py`
    2. 附件文件名裸 GBK 复现：`.scratch/repro_attachment_filename_gbk.py`

## 2026-10-23 转办核实

- 当前缺口仍存在，转 t026，无等价有效 backlog/active task。重新运行 `.scratch/repro_header_mojibake_gap.py`，default policy 路径出现替换符，保留原始报头字节后现有解码逻辑得到完整中文；`.scratch/repro_attachment_filename_gbk.py` 直接调用生产 parse_mime_content，将“测试文档.pdf”解析为含替换符乱码。

- 同类位点覆盖 archive.py 缺失元数据提取与附件 `filename`/`name` 两入口。真实不可恢复字节不得用猜测或替换符结果冒充成功；应验证持久错误、脱敏日志及派生产物一致性，不扩大为全局 IMAP 扫描降级策略变更。

- 已有 `test_blob_archive_fixes.py::test_archive_batch_backfills_missing_metadata_from_mime` 只覆盖 ASCII 回填；现有 MIME 测试未覆盖裸 GBK 报头与附件名、不可恢复解析损坏。t026 要求真实 PostgreSQL/BlobStore 贯通生产归档入口验证，不能只测 decoder。

- 产品边界未收到答复，已完整移交 t026 两项 UNVERIFIED-BLOCKING：是否保留原始 MIME 缺失元数据提取；不可恢复解析失败是否允许原文归档完成但 parse_error 显式失败。当前 spec 写明推荐语义，不视为产品批准；未确认前禁止 start。

- 本次不修改生产代码，不连接业务库，不执行历史修复；原条目关于已手动修复 14 封邮件属于历史记录，本次未重新验证。

- 处理：t026
