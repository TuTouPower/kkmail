# 账户连接与供应商设置

## 生效行为（t053）

- 添加与编辑按供应商展示连接方式、独立命名凭据字段和帮助图标；帮助弹窗关闭后恢复触发点焦点并保留草稿。
- Google 支持 Gmail API OAuth 与 IMAP 应用专用密码；Microsoft 仅 Graph OAuth，禁止可识别 Microsoft IMAP 接入。QQ/Foxmail、网易、iCloud、Yahoo、Zoho 提供 IMAP 预设与官方帮助，其他供应商保留自定义配置。
- 编辑保留原服务器、端口、TLS、登录名和协议；不按域名猜测改写既有配置。凭据不回显，空字段保留原值，非空凭据按字段合并。OAuth 凭据变更清除旧 Access Token，编辑与刷新通过加密行锁防止令牌轮换丢失。
- 当前实例不存在 Microsoft IMAP，未增加跨协议邮件身份迁移。成功保存不表示已经验证远端连接。
