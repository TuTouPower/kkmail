# d001 Python email 默认策略有损解码与报头缺陷检测机制

- 来源：t026
- 结论：Python `email.policy.default` 的 `get_content()` 默认采用 `errors='replace'` 静默有损替换；若需检测解码损坏必须显式传入 `errors='strict'`。报头与 RFC 2231/2047 参数中的编码异常不抛异常，而是作为 `UndecodableBytesDefect` 或 `CharsetError` 挂在报头对象的 `.defects` 属性上；引号内 RFC 2047 产生的 `InvalidHeaderDefect` 属于客户端普遍语法偏差，并非解码失败。
- 证据：
    1. `default.content_manager.get_handlers['text']` 源码中默认 `get_text_content(msg, errors='replace')`；
    2. 对非 ASCII 且未声明 charset 邮件，标准库回退 ASCII 触发 UnicodeDecodeError，需对未声明 charset 安全回退严格 UTF-8 校验；
    3. `tests/mail_core/test_archive_mime_parser.py` 及 `tests/mail_core/test_archive_decode_failure.py` 完整验证。
- 影响：MIME 解析模块 `src/mail_core/blobs/archive.py` 必须显式通过 strict 与 header/part defects 拦截解码损坏，避免静默吞错。
- 现状：有效
