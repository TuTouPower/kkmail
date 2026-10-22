# p011 IMAP报头未封装裸GBK编码导致主题与发件人乱码

- 现象：QQ 邮箱等服务拉取的历史邮件或系统通知在邮件列表和详情头部显示乱码（如 `V˥칫¹蚕˥Ж`、`Vu遚`、`亯¡í是u遚` 等含问号菱形替换符的错乱文字），但右侧 HTML 正文正常显示。
- 影响：用户无法辨识此类邮件的发件人和主题，搜索和列表展示受损。
- 根因：
    1. `src/mail_core/providers/imap.py:153` 在 `_parse_message_meta_from_fetch` 中处理服务端返回的原始 `header_bytes` 时，草率采用 `header_bytes.decode("utf-8", errors="replace")`。遇到腾讯等系统邮件直接在报头携带裸发 GBK/GB2312 字节时，多字节被 UTF-8 强行替换为 `\ufffd` 损坏；
    2. `src/mail_core/providers/imap.py:56` 在 `_decode_header` 中针对未指定 charset 的原始 chunk，直接以 `utf-8` 解码且无字符集嗅探回退。
- 测试缺口：现有 IMAP 测试夹具仅使用纯 ASCII 或标准 RFC 2047 UTF-8 封装编码（`=?UTF-8?B?...?=`），未覆盖携带裸发 GBK/GB2312 编码字节报头的兼容性场景。
- 线索：`.scratch/repro_imap_header_gbk_mojibake.py`
- 处理：t007
