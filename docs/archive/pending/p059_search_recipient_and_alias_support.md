# p059 邮件列表搜索与账号列表搜索支持收件人/别名

- 来源：用户提出
- 内容：
  1. 邮件列表搜索支持收件人：后端 `message_search` 索引目前仅覆盖 `subject`、`from_text` 与 `body_text`，未将 `to_addresses`（收件人及别名）纳入全文索引；需将其加入检索范围，使邮件列表搜索框输入收件人或别名（如 `user@example.com`、`alias@example.com`）可准确命中邮件。
  2. 账号列表分组及全局账号搜索支持收件人/别名：侧边栏分组及全局账号列表的搜索框目前仅匹配账号的 `email` 与 `display_name`；需支持按收件人别名检索匹配所属账号，定位到接收该别名邮件的账号。
- 处理：main
- 勘误注记：原非测试个人邮箱与别名已按开源合规要求脱敏替换为 RFC 2606 示例地址 user@example.com 与 alias@example.com。
