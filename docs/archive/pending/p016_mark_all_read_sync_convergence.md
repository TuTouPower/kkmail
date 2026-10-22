# p016 全部已读写回仅执行首批且旧同步覆盖本地状态，未读角标失真

- 现象：2504\*\*\*@qq.com 多次点击“全部已读”后仍出现未读。2026-10-22T19:01:02+08:00 只读核查：收件箱 1463 封，真实未读 66，folder_stats 缓存未读 40；66 条 mark_read 操作仍为 pending、attempts=0，且这 66 封本地均为未读，desired_state.is_read 却为 true；没有 pending/claimed 的 remote_operation_push 任务。该账号仅有 3 个已完成写回任务，日志各推送 20 条，共 60 条操作 done。
- 影响：全部已读不能持续收敛，刷新/后台同步后未读重新出现；侧栏和列表计数与实际记录不一致，计数降到 0 时前端还会禁用“全部已读”，使剩余操作难以触发。根因位于通用调度和同步路径，不限 QQ。已确认同类范围包含 mark_read、set_flag 的本地意图保护，以及写回批次续跑、瞬时错误重试、CAS 冲突后续跑。
- 根因：已通过生产逻辑及隔离 PostgreSQL 复现，属于产品逻辑缺陷。
    1. **写回续跑被当前任务吞掉**：sync/remote_push.py 的 push_remote_operations 默认 limit=20。worker/handlers.py 在任务仍为 claimed 时调用它；批次尾部、重试与 CAS 分支使用同一 remote-op-push:account_id 去重键入队。sync/jobs.py:enqueue_job 遇到 pending/claimed 同键任务直接返回当前任务，未形成后续执行；handler 随后将当前任务 complete 为 done，剩余操作便失去唤醒。用户下次点击最多再推进一批，不能保证清空。
    2. **旧远端状态覆盖尚未完成的本地意图**：sync/delta.py:\_apply_flag_patches 直接写 Message.is_read/is_flagged；sync/metadata.py:upsert_messages 也直接用远端元数据覆盖这些字段。两条路径均不检查同实体、同字段待推送操作。远端尚未收到已读写回时，旧未读状态能覆盖本地已读，但 pending 操作仍要求 is_read=true。账号只读快照的 66 条记录与此一致。
    3. **统计计算早于 ORM 写入**：db/session.py 明确 autoflush=False；\_apply_flag_patches 修改已有 Message 后未 flush，apply_delta_page 就调用 recompute_folder_stats。统计行已存在时，folder_stats.py 直接执行 SQL 聚合，读到旧状态；稍后 checkpoint/session.flush 才把新消息状态与错误统计一起落库。无变化后续 delta 又不会重算，偏差可持续存在。
- 已确认同类位点：
    - sync/remote_push.py 的 CAS 后 enqueue、限流/瞬时错误重试 enqueue、批次末尾剩余立即任务及未来 next_attempt_at 调度，均与正在执行的同键 claimed 任务冲突。隔离用例已验证首批余量、瞬时错误、CAS 三条实际 handler 路径。
    - mail/application/mutations.py 的单封已读、全部已读、旗标和删除均使用 \_wake_push 同键调度；执行中产生新操作也存在相同唤醒丢失窗口。CAS 用例在 provider 回调期间调用真实 set_message_read，已复现该窗口。
    - metadata upsert 与 delta flag patch 均缺字段级本地意图保护。已复现 metadata 覆盖 pending read，以及 delta 覆盖 pending read 和 pending flag。
    - delta flag-only 路径在已有统计行场景触发 flush 顺序缺陷；metadata upsert 自身已有 flush，不将其统计路径误列为相同机制。单封/批量已读经 enqueue 的 flush 后统计，在本次用例中能正确立即归零。
    - 扫描其他 enqueue_job 调用：delta 轮询与 archive 正常批次续跑未使用本次同键去重路径；不把所有后台调度一概列为已确认缺陷。
- 测试缺口：
    1. test_message_mutations_api.py:test_mark_all_read_api 仅断言接口成功、本地已读和紧接第二次 count=0，未运行实际 claimed → handler → 续跑 → complete 生命周期，也未注入旧远端同步。
    2. test_flag_convergence.py 的用例直接调用 push_remote_operations，缺真实 claimed WorkerJob，因此相同 enqueue 不会碰到正在运行的去重键；CAS 和离线恢复用例又由测试手动再次调用 push，掩盖唤醒丢失。
    3. test_delta_flag_patch.py 只验证主题/地址不被清空与 is_read 更新，未覆盖预先存在的 FolderStats 行、跨 session SQL 未读计数、pending 意图冲突。统计行首次创建会进入 begin_nested 并隐式 flush，不能替代“已有统计行”测试。test_folder_stats_race.py 使用固定聚合返回的 Mock，只测创建竞争，不能发现 ORM/DB 顺序问题。
    4. 补测：以 >20 条操作和真实 worker claim/complete 生命周期验证自动排空；覆盖运行期间新增操作、CAS 更新、瞬时错误及限流后的延迟唤醒，测试不得自行手动二次 push 充当产品调度。
    5. 补测：pending/in_progress 读状态与旗标操作分别交错 flag delta、metadata upsert，断言最新本地意图、远端完成后的最终收敛和不相关字段仍能同步；已完成操作与旧快照提交交错也须纳入修复设计验证。
    6. 补测：预建 FolderStats，使用生产 autoflush=False session，在提交后另开 session 比对 Message 实际未读、FolderStats 与统计 API；覆盖读→未读、未读→已读、重放无变化及前端按钮启用状态。
- 修复方向：保证每条剩余/未来重试/并发更新的 pending 操作都有持久化后续调度；同步尊重尚未收敛的最新本地字段意图；先持久化相关消息变更再聚合计数，并验证既有滞留队列的安全恢复路径。三处应形成同一修复交付，避免仅清缓存或反复点击掩盖问题。
- 核实边界：
    - 未点击真实账号“全部已读”、未调用实际远端写回、未修改生产 DB、未重置游标或重启业务服务。运行态证据全部来自 BEGIN READ ONLY 查询和日志。
    - worker 容器与当前源码的 sync/jobs.py、sync/remote_push.py、sync/metadata.py、sync/delta.py、mail/application/mutations.py、db/session.py SHA-256 一致，排除这六个模块的构建版本差异。
    - QQ 另有非收件箱目录 UID SEARCH 返回 NO，导致账号 sync_status=failed；该观察尚不构成本症状根因，不将其混入本条已确认修复范围。收件箱既有写回成功记录和当前未尝试队列不能证明 QQ 当前凭据永远有效，也不需要以凭据失效解释已复现应用缺陷。
    - effective status 已查重：t006 active，t007–t010 backlog；t008 涉及新目录 scope，但不包含本条调度、意图覆盖与统计顺序问题，无等价 task。
- 线索：
    - `.scratch/unread_repro/repro.py`：调用真实 mark_all_messages_read、claim_jobs、handle_job、apply_delta_page、upsert_messages；provider 仅用离线 Stub，不连接邮箱。
    - `.scratch/unread_repro/run_repro.py`：以现有 API 镜像启动独立测试容器；PostgreSQL 仅监听 scratch 下 Unix socket、无网络；测试结束停止临时 DB，真实业务容器不变。
    - `.scratch/unread_repro/result.json`：六组断言通过。26 条全部已读 → 20 done + 6 pending + 0 活跃写回任务；旧 delta 后实际未读 6、缓存 0；metadata/read、delta/flag、瞬时错误与 CAS 续跑均复现。
    - `.scratch/unread_repro/live_snapshot.sql` / `live_snapshot.json`：脱敏只读运行态快照；不含凭据或邮件正文。
- 处理：t012
