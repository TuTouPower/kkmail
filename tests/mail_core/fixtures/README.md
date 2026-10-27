# mail-core L2 集成测试夹具 (Fixtures)

|目录路径|职责说明|
|---|---|
|`dovecot/`|Alpine Dovecot 容器镜像 + 预置初始数据的 Maildir 目录（账号：`alice@kkmail.test` / 密码：`alice-imap-pass`）|
|`maildir/`|相同的邮箱目录布局，用作 pymap 内存回退|

## 启动与运行

```bash
docker compose -f docker-compose.mail-core.yml up -d --build imap
# 或者使用脚本一键拉起
./scripts/start-mail-core-imap.sh

export MAIL_CORE_IMAP_PORT=1143
pytest tests/mail_core/test_imap_provider_live.py -q
```
