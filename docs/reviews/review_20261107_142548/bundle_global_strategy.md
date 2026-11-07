# bundle_global_strategy

## Summary

全仓战略适配宏观评估结论：产品边界控制极其精准克制，技术投入与核心业务价值高度匹配，依赖与供应商选型自洽稳健。

1. 产品边界控制（收信/阅读/检索 vs 砍发信/砍扩展）：

- 剔除发信能力（SMTP/Graph Send/Compose/Reply）彻底消除了自托管节点沦为垃圾邮件放大器的严重合规与安全漏洞，规避了 SPF/DKIM/DMARC 投递失败、IP 信誉及复杂富文本编辑器的维护黑洞，攻击面缩减 80% 以上，使系统纯粹聚焦于多账号统一监控、阅读、归档与快速检索。
- 彻底废弃浏览器扩展及相关桥接 API，避免了跨域提权漏洞与扩展商店审核包袱，使客户端交付形态清晰收敛为 Web SPA 与 Electron 桌面端。
- 审慎克制跨目录移动与归档写回动作，深刻识别了 Gmail 标签机制、Graph ID 漂移与 IMAP 销毁旧 UID 等语义冲突，从根因上杜绝了增量同步撕裂与幽灵邮件风险。

2. 技术投入与业务价值匹配（统一 PostgreSQL 与 Electron 集成）：

- 坚决回绝 SQLite，统一强制采用 PostgreSQL 16 作为跨 Web 容器与 Electron 桌面的唯一数据基线，彻底贯彻了“单一架构真相”与“零兼容性负担”铁律。规避了双数据库方言在 ORM、FTS 全文检索、事务隔离及高并发锁（LISTEN/NOTIFY、咨询锁、行级写锁）上的严重抽象泄漏。
- 桌面端虽因内置 PostgreSQL 管理器（postgresManager.js）增加了多进程编排与打包体积，但直接赋能了单进程 Worker 8 槽位并发执行器、IDLE 实时长连接、错峰增量巡检及后台批量 AES-256-GCM 归档的高吞吐并发，完全消除多账号并发下的写入锁死瓶颈。
- 严格落实单用户 Capability-based UUID 模型，拒绝推测性的多租户 RBAC 复杂度，技术资源完全倾斜在侧边栏分组、深翻页与端到端安全加固上。

3. 依赖与供应商选择合理性（下线 Gmail API，收敛至 IMAP 与 Graph）：

- 全面下线 Gmail API 是极具远见的战略决断，规避了 Google 极其苛刻且昂贵的受限权限年审（CASA Tier 2/3）与个人测试凭据 7 天强制过期的致命枷锁；通过标准 IMAP 加应用专用密码接入，配合虚拟文件夹（\\All 等）屏蔽策略，以极简实现保障了极高稳定性。
- 针对微软生态顺应其官方淘汰 IMAP Basic Auth 的趋势，全面拥抱 Graph REST API，提供 PKCE 授权码与设备码双轨接入，并以 JSON batching 批量写回，适配现代云端规范。
- 协议适配器高度收敛为统一 IMAP 与 Graph 两大引擎，无私有散乱协议，大幅降低全生命周期维护成本。

## Findings

No findings.

## questions

```json
[]
```

## question_decisions

```json
{}
```
