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
- 处理：未开
