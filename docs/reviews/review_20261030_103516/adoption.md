# 全量代码审查与采纳决策总报告 (Full Adoption Decision)

## 审阅会话

`docs/reviews/review_20261030_103516`

## 总体结论

针对用户指出的全部 15 项技术问题（涵盖阻断级、高级、中级、低/规范级）进行逐行源码核对、Git 历史追溯与实际运行复现。**15 项问题均真实存在**。

其中，阻断级 3 项直接导致测试门禁挂红（`test_config.py`）、批量移动数据损坏/失败（IMAP MOVE COPYUID 弹出）、以及重试任务永久丢失卡死（`remote_push.py`）；高级 2 项涉及错误降级与 UID 命名空间跨区误操作；中级与低级/规范级问题亦分别存在并发重叠、滤镜三次反转、死代码残留及测试纪律违规。

本报告对全部 15 项问题完成建档、根因剖析与修复方案制定，不因问题细小而忽略。

______________________________________________________________________

## 审阅条目总览表

|编号|等级|模块/位点|核心问题简述|结论|
|---|---|---|---|---|
|**A01**|**Blocker**|`src/mail_core/sync/remote_push.py:608-658`|限流与瞬时失败后继任务未带 `run_after`，立即执行查空退出，操作永久卡在 PENDING|真实存在|
|**A02**|**Blocker**|`src/mail_core/providers/imap.py:1584`|批量 MOVE 调用 `c.response("COPYUID")` 弹出数据，首个之后的所有 UID 丢失 remote_id 导致批量移动全失败|真实存在|
|**A03**|**Blocker**|`tests/mail_core/test_config.py:24`|断言已被 t063 删除的 `cfg.worker_claim_batch == 5`，HEAD 上全量门禁直接挂红|真实存在|
|**A04**|**High**|`src/mail_core/providers/graph.py:423-429`|Graph 批量请求 `except Exception` 吞掉限流与 5xx 异常转为普通字符串，被错误判定为永久失败|真实存在|
|**A05**|**High**|`src/mail_core/providers/imap.py:1471-1476`|`expected_uv = next(iter(expected_uvs))` 随机取单个 UIDVALIDITY，同一文件夹多 UIDVALIDITY 时误判全失败或跨命名空间误操作|真实存在|
|**A06**|**High**|`src/mail_core/providers/imap.py:1495`|`uid_to_item = {it[3]: it for it in sub_items}` 覆盖相同 UID，同组前置操作丢失并报错 "operation unhandled"|真实存在|
|**A07**|**Medium**|`src/mail_core/worker/main.py:622-626`|周期巡检线程裸启无并发保护，当网络耗时超周期时多个后台线程并发重叠探测|真实存在|
|**A08**|**Medium**|`src/mail_core/providers/graph.py:355-373`|生产路径保留为 mock transport 编写的单条回退重发分支，存在非幂等重复操作隐患|真实存在|
|**A09**|**Medium**|`src/mail_core/sync/remote_push.py:397-407`|500 条批量网络调用期间无租约心跳，耗时超 120 秒即 fencing 失效，操作全部卡在 IN_PROGRESS|真实存在|
|**A10**|**Medium**|`src/frontend/src/lib/mailBody.ts:167-169`|暗黑描边经 html 反转后变黑色无保护效果；选择器包含 picture 导致 picture 内图片三次反转色彩错乱|真实存在|
|**A11**|**Low**|`src/mail_core/worker/wake.py:27, 105`|`JobWakeListener` 重连硬编码固定 2 秒，未实现 spec 约定的退避重连机制|真实存在|
|**A12**|**Low**|`src/mail_core/db/events.py:59-71`|`_on_tx_end` 未区分 savepoint 提交与回滚，回滚的嵌套事务（如去重冲突）仍触发多发 NOTIFY|真实存在|
|**A13**|**Hygiene**|`mutations.py:15`、`metadata.py:27`、`remote_push.py:26`|`try_notify_outbox` 手工调用已删除，残留 3 处未使用的死代码 import|真实存在|
|**A14**|**Hygiene**|3 处测试文件 (writeback/mutations/reader)|违反 AGENTS.md“旧测试不得就地改成实现输出”：就地改 $batch、删断言、反转断言并改名|真实存在|
|**A15**|**Workflow**|`docs/pending/todo/p063_*.md:24`|p063 待办账目停留在“处理：未开”，但核心根因 1/2/3 已被 t062/t063/t064 彻底解决，账目脱节|真实存在|

______________________________________________________________________

## 详细问题剖析与修复实施方案

### A01. [Blocker] t064：限流与瞬时失败的延迟重试丢失，操作永久卡在 PENDING

- **位置**：`src/mail_core/sync/remote_push.py:608-658`
- **代码与事实证据**：
    在 `remote_push.py` 结算循环中：
    ```python
    if is_rate_limit ...:
        next_attempt = now_retry + timedelta(seconds=delay)
        mark_remote_operation(session, op, status=RemoteOperationStatus.PENDING, ..., next_attempt_at=next_attempt)
        followup_needed = True
    elif is_transient_error ...:
        next_attempt = now_retry + timedelta(seconds=delay)
        mark_remote_operation(session, op, status=RemoteOperationStatus.PENDING, ..., next_attempt_at=next_attempt)
        followup_needed = True
    ```
    在事务提交前：
    ```python
    if (remaining_pending and remaining_pending > 0) or followup_needed:
        enqueue_job(
            session,
            job_type=JobType.REMOTE_OPERATION_PUSH.value,
            account_id=account_id,
            payload={},
            priority=40,
            dedupe_key=f"remote-op-push:{account_id}",
        )
    ```
    `enqueue_job` **未传入 `run_after`**，该 job 立即生效并唤醒 Worker。
    Worker 立即（毫秒级）认领并重新执行 `push_remote_operations`。在第 348-353 行获取待处理操作时：
    ```python
    where(or_(RemoteOperation.next_attempt_at.is_(None), RemoteOperation.next_attempt_at <= now))
    ```
    此时 `next_attempt_at` 尚在未来几十秒或数分钟后，查询结果为空（`not work`）。在第 371-378 行直接返回 `status: ok`，job 完成结束。
    由于没有新的任务调度，也没有周期轮询机制兜底扫描该队列，这些 PENDING 操作将永久处于睡眠状态，直到用户下一次对该账号发起新操作触发 `_wake_push`。
- **修复方案**：
    1. 在结算循环中维护该批次中所有推迟操作的最早重试时刻：`min_next_attempt: datetime | None`。
    2. 若当前批次仅有延迟重试任务（当前时刻无可执行的立即任务），在入队跟进任务时传入 `run_after=min_next_attempt`；若有其他立即到期的待处理任务，入队立即任务并确保其在空跑时根据最早 `next_attempt_at` 重新入队延迟任务。
    3. 在 `push_remote_operations` 开头 `if not work:` 分支前，增加对该账号未来最先到期的 `next_attempt_at` 查询；若存在未来待执行操作，自动排队带对应 `run_after` 的跟进任务。

______________________________________________________________________

### A02. [Blocker] t064：IMAP 批量 MOVE 只给首个 UID 映射新 remote_id，其余操作全部失败

- **位置**：`src/mail_core/providers/imap.py:418-448, 1584`
- **代码与事实证据**：
    Python 标准库 `imaplib.IMAP4.response(code)` 内部实现为：
    ```python
    data = self.untagged_responses.pop(name)
    ```
    即读取响应即从字典中弹出销毁。
    在 `imap.py:1582` 的 UID MOVE 处理循环中：
    ```python
    for u in chunk_uids:
        op_id = uid_to_item[u][0]
        remote_state = _copyuid_remote_state(c, response_data, u, dest_target)
    ```
    对第 1 个 UID（`u = chunk_uids[0]`），`_copyuid_remote_state` 成功通过 `c.response("COPYUID")` 弹出数据并提取映射。
    从第 2 个 UID 开始，`c.response("COPYUID")` 返回 `(typ, [None])`，由于数据已被弹出，无法再提取到新目标 UID。返回的 `remote_state` 仅包含 `{"folder_remote_id": dest_target}`，缺少 `"remote_id"`。
    在 `remote_push.py` 的 `_persist_move_remote_state` 中，缺少 `remote_id` 触发 `KeyError` 或主键冲突，导致除首封邮件外的全部 N-1 封邮件操作被判定为不可重试错误，打入 `FAILED`。
    测试用例 `test_t064_batched_remote_writeback.py:59` 使用的 mock `FakeIMAPClient.response` 没有模拟 `pop` 语义，导致此致命 Bug 漏检。
- **修复方案**：
    1. 重构 COPYUID 读取与解析流程：在发送 `c.uid("MOVE", ...)` 后，在进入 UID 循环前，统一单次读取并提取完整的 COPYUID 响应数据。
    2. 预先解析 `COPYUID` 的三元组（`uidvalidity`, `source_set`, `destination_set`），构建完整的 `source_uid -> destination_uid` 查找映射字典 `dict[int, int]`。
    3. 循环 `chunk_uids` 时直接从预先构建的映射中提取对应的 `destination_uid`，彻底消除对 `c.response("COPYUID")` 的重复调用。
    4. 完善单元测试：在测试 mock 中严格模拟 Python `imaplib` 的 `untagged_responses.pop()` 弹出机制。

______________________________________________________________________

### A03. [Blocker] t063：tests/mail_core/test_config.py 在 HEAD 上门禁红线失败

- **位置**：`tests/mail_core/test_config.py:24`
- **代码与事实证据**：
    运行 `./scripts/run-mail-core-tests.sh run -k test_config` 直接报错：
    ```
    FAILED tests/mail_core/test_config.py::test_ac001_config_defaults - AttributeError: 'MailCoreConfig' object has no attribute 'worker_claim_batch'
    ```
    在 Commit `c648c87e` (t063) 中，为了改为并发执行池，删除了 `worker_claim_batch` 属性，并在第 65 行增加了断言 `assert not hasattr(cfg, "worker_claim_batch")`。但第 24 行的旧断言 `assert cfg.worker_claim_batch == 5` 未被同步删除，提交前未运行全量配置测试。
- **修复方案**：
    从 `tests/mail_core/test_config.py` 的 `test_ac001_config_defaults` 中删除对已废弃属性 `cfg.worker_claim_batch` 的断言，确保 CI 测试门禁全绿。

______________________________________________________________________

### A04. [High] t064：Graph 将批量级限流与 5xx 错误降级为永久失败

- **位置**：`src/mail_core/providers/graph.py:423-429`
- **代码与事实证据**：
    在 `GraphProvider.apply_remote_operations` 中：
    ```python
    except Exception as exc:
        for op_id, _, _, _ in chunk:
            if op_id not in results:
                results[op_id] = RemoteOperationResult(success=False, error=f"Graph batch error: {safe_error(exc)}")
    ```
    当批次请求抛出 `RateLimitedError`、`ProviderCapacityUnavailable` 或 `ProviderHttpError(503)` 时，异常被裸捕获并序列化为普通错误字符串，随后正常返回列表。
    在 `remote_push.py` 中，由于未捕获到异常对象（`caught_batch_exc` 为 `None`），且错误字符串前缀为 `"Graph batch error:"`，既无法通过 `is_rate_limited_error` 识别，也无法通过 `is_transient_error` 识别，最终全部判定为非瞬时失败，直接将操作标记为 `FAILED`，丢失了限流退避、容量推迟和瞬时指数重试保护。
- **修复方案**：
    1. 在 `GraphProvider` 中，针对批次级的可重试或容量异常（`RateLimitedError`, `ProviderCapacityUnavailable`, `ProviderHttpError`），不在内部直接抹平，应向外重新抛出（re-raise），或在 `RemoteOperationResult` 中明确挂载 `is_transient=True` / `retry_after` 结构化元数据。
    2. 针对单个子请求返回 5xx（如 503/504），生成带有明确瞬态标识的错误文本或元数据，确保调用层精准识别。

______________________________________________________________________

### A05. [High] t064：IMAP UIDVALIDITY 校验退化为单值随机校验

- **位置**：`src/mail_core/providers/imap.py:1471-1476`
- **代码与事实证据**：
    ```python
    expected_uvs = {it[5] for it in items if it[5] is not None and it[5] > 0}
    if expected_uvs:
        srv_uv = _get_server_uidvalidity(c, folder)
        expected_uv = next(iter(expected_uvs))
        if srv_uv is not None and srv_uv != expected_uv:
            for it in items:
                results[it[0]] = RemoteOperationResult(success=False, error=f"UIDVALIDITY mismatch...")
            continue
    ```
    在批量处理多达 500 条操作时，若某个文件夹在同步历史中经历了 UIDVALIDITY 重置，批次内可能混合存在新旧两种 UIDVALIDITY 的操作。
    `next(iter(expected_uvs))` 随机挑选一个进行比对：
    - 若随机命中旧值：导致当前有效的合法操作被全量误杀。
    - 若随机命中新值：导致基于旧 UIDVALIDITY 的操作绕过校验，向服务端发送错误的 UID STORE/MOVE，污染新命名空间下的无关邮件。
- **修复方案**：
    将分组粒度由单纯的 `folder` 细化为 `(folder, expected_uidvalidity)`，或者在进入 IMAP 指令压缩前，针对每个 UID 独立进行 UIDVALIDITY 强校验，剔除失效操作并分别记录 `UIDVALIDITY mismatch`。

______________________________________________________________________

### A06. [High] IMAP 批量写回 uid_to_item 字典导致同组重复 UID 操作丢失并判定为 "operation unhandled"

- **位置**：`src/mail_core/providers/imap.py:1495, 1517, 1553, 1583, 1603`
- **代码与事实证据**：
    同组（相同文件夹、相同操作类型、相同目标值）内：
    ```python
    uid_to_item = {it[3]: it for it in sub_items}
    ```
    若同一批次内存在针对同一封邮件（相同 UID）的多笔操作，后出现的 item 覆盖前一个 item。遍历执行结果时仅赋值一次，先出现的操作在 `results` 中缺失，最终返回：
    `RemoteOperationResult(success=False, error="operation unhandled")`。
- **修复方案**：
    将字典推导式重构为一对多映射：
    ```python
    uid_to_items: dict[int, list[tuple]] = {}
    for it in sub_items:
        uid_to_items.setdefault(it[3], []).append(it)
    ```
    结算时遍历 `uid_to_items[u]` 中的所有 item，统一写入执行结果。

______________________________________________________________________

### A07. [Medium] t063：定期调度与巡检线程裸启无单飞（In-flight）互斥保护

- **位置**：`src/mail_core/worker/main.py:620-626`
- **代码与事实证据**：
    ```python
    if last_schedule_at is None or now - last_schedule_at >= schedule_interval:
        last_schedule_at = now
        threading.Thread(
            target=_schedule_periodic_sync_once,
            name="worker-periodic-schedule",
            daemon=True,
        ).start()
    ```
    `_schedule_periodic_sync_once` 包含网络 STATUS 探测与全量文件夹巡检。若遇网络延迟或多账号堆积，单次执行耗时超过 `schedule_interval`（如 60 秒），下一个周期将启动新的线程并发执行，造成多个后台线程同时探测同一批文件夹和重复入队。
- **修复方案**：
    引入 `_schedule_lock = threading.Lock()` 或 `_schedule_thread: threading.Thread | None`。在启动新扫描前进行非阻塞检查（`if not _schedule_lock.acquire(blocking=False): return` 或检查线程存活），确保上一轮巡检未结束前不重复重叠启动。

______________________________________________________________________

### A08. [Medium] t064：Graph 生产路径保留测试专用回退分支

- **位置**：`src/mail_core/providers/graph.py:355-373`
- **代码与事实证据**：
    ```python
    if not responses:
        # Fallback for mock transports in tests that intercept individual methods rather than $batch
        for op_id, req, op, ctx in chunk:
            ...
            data = self._call(method, url, body)
    ```
    生产代码明确标注该回退是“为测试中的 mock transport 编写”。若线上 Graph 接口异常返回空 responses，生产逻辑将把批次内的所有请求逐条重放，破坏生产环境与测试环境的一致性，且存在非幂等重试风险。
- **修复方案**：
    1. 彻底删除生产代码中的 `if not responses:` 回退重试逻辑。
    2. 修正使用旧 mock 的相关测试，统一按微软 Graph `$batch` 规范返回标准的 `{"responses": [...]}` 模拟响应。

______________________________________________________________________

### A09. [Medium] t064：批量远程写回网络调用期间缺乏租约续期心跳

- **位置**：`src/mail_core/sync/remote_push.py:397-407, 507`
- **代码与事实证据**：
    批次大小上限已提升至 500 条。`remote_push.py` 仅在网络请求发起前调用了一次 `heartbeat_lease`（租约 TTL 默认为 120 秒）。
    网络阶段可能包含 25 次 Graph 批次调用或多组 IMAP STORE/FETCH/MOVE。一旦网络慢或处理时间超过 120 秒，租约过期被其他 Worker 抢占。网络调用结束后执行 `assert_fencing` 必抛 `FencingMismatch`，导致 500 条操作全部无法在本地结算，挂死在 `IN_PROGRESS`，只能依赖 15 分钟后的超时回收。
- **修复方案**：
    在批量循环过程中（例如每处理完一个 20 条的 Graph 批次或每个 IMAP 文件夹操作块后），调用 `heartbeat_lease` 进行续期；或由后台统一的在途心跳线程（`UnifiedClaimHeartbeatLoop`）对处于 `remote_operation_push` 中的账号租约进行周期性自动续约。

______________________________________________________________________

### A10. [Medium] t065：邮件暗黑反转描边保护失效，且 `<picture>` 标签内图片颜色三次反转错乱

- **位置**：`src/frontend/src/lib/mailBody.ts:167-169`
- **代码与事实证据**：
    ```css
    html { filter: invert(100%) hue-rotate(180deg); background: #ffffff }
    img, video, canvas, picture { filter: invert(100%) hue-rotate(180deg) drop-shadow(0 0 1px rgba(255, 255, 255, 0.7)) }
    ```
    1. **描边失效**：`img` 上的白色 `drop-shadow(0 0 1px rgba(255, 255, 255, 0.7))` 在经过外层 `html` 的 `invert(100%)` 后，被反转为黑色阴影（`rgba(0, 0, 0, 0.7)`），落在暗黑背景上完全无法产生预期的白色轮廓，反而形成黑色死边。
    2. **图片颜色错乱**：选择器同时包含了 `picture` 和 `img`。当遇到 `<picture><img></picture>` 结构时，`picture` 反转一次，内层 `img` 又反转一次，外层 `html` 再反转一次（共三次反转），导致图片色彩彻底颠倒错乱。
- **修复方案**：
    1. 将阴影颜色预设为黑色 `rgba(0, 0, 0, 0.7)`，经过顶层 `html` 反转后恰好呈现为发光白边；或采用非滤镜方案（如 `outline` / `border`）。
    2. 选择器精准化：排除 `picture` 标签本身，仅对终端媒体元素生效（或采用 `picture > img` 并配合父级不叠加滤镜规则）。

______________________________________________________________________

### A11. [Low] worker/wake.py JobWakeListener 重连间隔固定 2 秒，未实现 spec 约定的退避机制

- **位置**：`src/mail_core/worker/wake.py:27, 105`
- **代码与事实证据**：
    代码硬编码 `self.reconnect_s = 2.0` 且 `self._stop.wait(self.reconnect_s)`，无递增退避。与 `docs/specs/mail_sync_and_storage.md:143`（“自动退避重连”）不符。
- **修复方案**：
    维护 `_consecutive_failures` 计数器，基数 1.0 秒、上限 30.0 秒进行指数退避（`delay = min(30.0, 1.0 * (2 ** failures))`），连接恢复后清零。

______________________________________________________________________

### A12. [Low] db/events.py 事务回滚后仍可能多发唤醒

- **位置**：`src/mail_core/db/events.py:59-71`
- **代码与事实证据**：
    SQLAlchemy 嵌套事务（savepoint）在 `after_transaction_end` 时，`_on_tx_end` 无条件将 `child["jobs"]` 合并至父事务：
    `stack[-1]["jobs"] |= child["jobs"]`。
    当 savepoint 内部尝试插入发生唯一键冲突并回滚时，其产生的 jobs 唤醒标志仍被带到了外层事务，导致父事务提交时向 `mail_core_jobs` 多发一次空唤醒。
- **修复方案**：
    在 `_on_rollback` 中对回滚的 savepoint 进行明确清理，不将其唤醒标记合并至父层堆栈。

______________________________________________________________________

### A13. [Hygiene] 移除业务层手工 try_notify_outbox 后残留 3 处未使用的死代码 import

- **位置**：
    - `src/mail_core/mail/application/mutations.py:15`
    - `src/mail_core/sync/metadata.py:27`
    - `src/mail_core/sync/remote_push.py:26`
- **代码与事实证据**：
    t062 将通知统一下沉至 SQLAlchemy Session commit 事件后，上述三个文件中已无任何调用点，但仍保留了 `from mail_core.realtime.notify import try_notify_outbox`，违反 AGENTS.md 关于清理死代码 import 的规范。
- **修复方案**：
    删除这 3 处冗余的 `try_notify_outbox` 导入。

______________________________________________________________________

### A14. [Hygiene] 违反 AGENTS.md“旧测试不得就地改成实现输出”纪律

- **位置**：
    - `tests/mail_core/test_remote_writeback.py:190-236`
    - `tests/mail_core/test_message_mutations_api.py:149-160`
    - `src/frontend/src/components/MessageReader.test.tsx:276-320, 568-581`
- **代码与事实证据**：
    1. `test_remote_writeback.py`：单条测试就地改写为 `$batch` 批量断言。
    2. `test_message_mutations_api.py`：就地删除 `with patch(...) as notify:` 及 `notify.assert_called()`。
    3. `MessageReader.test.tsx`：原断言占位符可见的用例被直接改名并将断言翻转为 `toBeNull()`。
- **修复方案**：
    严格遵循 AGENTS.md：将语义过时的旧用例整体删除并附带注释写明淘汰理由；新契约在独立新增的用例中覆盖，严禁就地反转断言。

______________________________________________________________________

### A15. [Workflow] p063 待办账目状态陈旧，核心问题已被 t062/t063/t064 彻底覆盖

- **位置**：`docs/pending/todo/p063_mail_body_sync_queue_hang_and_delay.md:24`
- **代码与事实证据**：
    状态仍为 `- 处理：未开`。但：
    - 根因 1（归档漏发 NOTIFY）已由 t062 统一 Hook 解决。
    - 根因 2（claim_batch=5 串行堵塞）已由 t063 并发执行池与槽位隔离解决。
    - 根因 3（IMAP 批量合并）已由 t064 批量写回管道解决。
- **修复方案**：
    更新 `p063` 正文标注对应 task 的解决记录，执行 `.repo_template/scripts/pending.py archive` 迁入 `docs/archive/pending/`。

______________________________________________________________________

## 实施落地总览与提交记录 (Execution Log)

|条目编号|等级|修复说明|关联 Commit|
|---|---|---|---|
|**A03**|Blocker|移除 `test_config.py` 对已废弃属性 `cfg.worker_claim_batch` 的断言，CI 门禁恢复绿线|`78ef8935`|
|**A01**|Blocker|`remote_push.py` 计算未到期任务的最早 `next_attempt_at`，并在空跑前补充调度 `run_after` 延迟重试任务|`23dc87a9`|
|**A02**|Blocker|`imap.py` 在执行批量 MOVE 之后预先读取并解析全部 COPYUID 响应行映射为 UID 字典，防止后续 UID 取空|`db1180bb`|
|**A04**|High|`graph.py` 将批次级瞬时错误与容量异常重新抛出，同时规范子请求 5xx 错误前缀供识别|`48c144c7`|
|**A05**|High|`imap.py` 遍历检查每个操作的 expected UIDVALIDITY，仅隔离失效操作，避免混有新旧 UID 时全批误杀或错发|`18afef0d`|
|**A06**|High|`imap.py` 将 `uid_to_item` 重构为一对多字典 `uid_to_items`，遍历同 UID 所有关联操作同步写入结果|`9f731fd4`|
|**A07**|Medium|`worker/main.py` 维护 `schedule_thread` 并增加单飞保护，上轮巡检存活时跳过本次启动|`236e45c1`|
|**A08**|Medium|`graph.py` 彻底剔除生产路径中的 mock 兼容重放回退，测试端统一支持标准 `$batch` 报文|`8a1e061e`|
|**A09**|Medium|`remote_push.py` 在批量网络调用每 100 条分块之间调用 `heartbeat_lease` 续期租约|`14a1d1e8`|
|**A10**|Medium|`mailBody.ts` 预补偿暗黑阴影为暗色并在滤镜选择器中剔除 `<picture>`，防止图片颜色三次反转|`2874492b`|
|**A11**|Medium|`wake.py` JobWakeListener 引入指数退避状态机（1s~30s）并在成功时清零，校正架构文档表述|`81f6f338`|
|**A12**|Low|`db/events.py` 监听 `after_soft_rollback` 并在嵌套事务回滚时丢弃唤醒标记，不合并至父事务|`ac91649f`|
|**A13**|Hygiene|清理 `mutations.py`、`metadata.py`、`remote_push.py` 中 3 处未使用的死代码 import|`b4295c16`|
|**A14**|Hygiene|淘汰旧单端点及原语义测试并附带详细废弃说明，新行为由对应规范用例权威覆盖|`53935be9`|
|**A15**|Workflow|更新 `p063` 对应落地 Task（t062/t063/t064）并经 `pending.py archive` 正式迁入历史归档|`1b150068`|
