# p040 拉信超时设置未接入 provider，设置页占位值掩盖实际默认值

- 现象：用户看到设置页“拉信超时（秒）”显示 120，预期请求受其约束。2026-10-24 本机 API 容器只读检查：stored_value=null，get_fetch_timeout_seconds 回退为 30；前端实际值为空时用 placeholder="120"，并非已生效配置。即使保存 120，provider 工厂也不读取该设置。
- 影响：按需正文归档、后台同步等共享 build_provider 路径；IMAP 与 Gmail/Graph HTTP 请求实际超时不随设置变化。用户无法根据设置判断请求何时结束，排查容易误把 15 分钟 claim 回收阈值当拉信超时。
- 根因：产品缺陷。get_fetch_timeout_seconds 只有定义、导出与测试，无生产调用；factory.build_provider 创建 ImapProvider 未传 timeout，使用默认 30 秒；providers/oauth.py 的 token POST 固定 timeout=30、邮件 API urlopen 固定 timeout=60。单个 socket/HTTP 等待超时并非整次多阶段拉取的总 deadline，HTTP 重试也可能累计超过单次超时。SettingsModal 的未设置状态只呈现 120 占位值，未显示真实默认值或作用范围。
- 测试缺口：test_settings_store 只测存储、校验与 helper 读取，前端测试只断言保存值，未从已保存配置验证实际 provider/transport 的 timeout。应补设置→构造→网络调用链路测试，覆盖 IMAP、Gmail/Graph、token 刷新及重试边界；明确拉信超时究竟约束单次网络等待还是整体拉取，按产品契约断言取消/失败反馈与 claim 收尾。前端补未配置、已配置显示与后端有效默认值一致性测试。不得将网络超时与 claim 回收、租约 TTL 混为同一计时器。
- 线索：`.scratch/body_sync_flicker/timeout_setting_repro.py` 以无网络、无 DB 写入替身令 helper 读到 120，调用真实 build_provider 后仍得到 ImapProvider.timeout=30；结果在 timeout_setting_result.txt。代码：accounts/settings_store.py、providers/factory.py、providers/imap.py、providers/oauth.py、frontend SettingsModal.tsx、api/client.ts。前端 HTTP transport 自身默认 30 秒，sync-body 未覆盖 timeoutMs，与服务端设置同样独立。
- 处理：未开

关联：p039 负责按需归档残留占用、无限请求及运行阶段日志；本条负责超时配置接线与有效值展示。不把“15 分钟才回收”当作单个网络请求持续运行 15 分钟的证据。
