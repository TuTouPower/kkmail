# bundle_global_system_properties

## Summary

系统各部分组合后的整体性质审查结论：核心安全、一致性、可靠性与性能资源上限承诺均严格成立，整体架构具备坚实的防御深度与工程鲁棒性。具体表现为：1. 安全域：图片代理结合底层套接字直连与双重校验彻底杜绝了 SSRF 与 DNS Rebinding 风险，前端受控沙箱 iframe 配合严苛的 CSP 与 DOMPurify 剥离实现了正文不可信输入与宿主上下文的彻底物理隔离；防暴力破解限流器具备 O(1) 淘汰与内存上限保护；session_epoch 驱动的会话撤销在单进程及长连接 SSE 维度即时生效（跨进程 REST 请求存在 5s 缓存 TTL 窗口）。2. 可靠性与一致性域：Outbox 基于单例行行锁分配全局递增 publication_seq，彻底消除并发空洞漏读；SSE 具备基于 Last-Event-ID 的断点续传及全量重对齐安全降级（resync_hint）；多账号同步基于 PostgreSQL 行排他锁与单调递增 fencing_token 实施多粒度断言，严格杜绝脑裂与脏写覆盖。3. 性能与容量域：基于 PG 咨询锁的 8 槽位全局出站配额与前后台流量分级（0-1 预留前台交互，2-7 后台归档）彻底避免了大量后台同步饿死用户交互；SSE 连接数受 128 上限保护；前端采用基于 rAF 帧对齐节流的定高轻量虚拟列表，渲染万级邮件 DOM 节点恒定在数十个，保证了极致流畅度。

## Findings

- [Low][95] src/mail_core/realtime/listener.py:105-110 — 跨进程场景下 session_epoch 撤销对 REST API 存在最长 5 秒缓存窗口
    - ID: f_sys_session_revocation_multiprocess_window; verification: static
    - Evidence: src/mail_core/realtime/listener.py:105-110 中 \_handle_notification 收到 SESSION_REVOCATION_CHANNEL 时仅调用了 self.dispatcher.close_session_streams(current_epoch=current_epoch); src/mail_core/security/auth.py:388-392 中 get_session_epoch 使用了 \_SESSION_EPOCH_CACHE_TTL_SECONDS = 5.0 的进程内缓存，且 listener 未通知或清理 auth 模块中的 \_session_epoch_cache
    - Impact: 在多工作进程或分布式部署场景下，用户修改密码或注销后，长连接 SSE 会被立刻切断，但其他工作进程对无状态 REST API 请求仍会在最长 5 秒的 TTL 窗口内信任旧凭据。在桌面单进程环境下无影响。
    - Fix: 在 src/mail_core/realtime/listener.py 收到 SESSION_REVOCATION_CHANNEL 广播时，同步调用 mail_core.security.auth 中的缓存更新函数或清空 \_session_epoch_cache，消除跨进程撤销延迟。

## questions

```json
[]
```

## question_decisions

```json
{}
```
