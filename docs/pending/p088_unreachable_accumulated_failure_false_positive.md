---
pid: "p088"
slug: "unreachable_accumulated_failure_false_positive"
status: "closed"
resolution: "transferred"
reason: "已核实非连续累计与非网络错误误判两条根因及全部同类位点，转交 t087 根治状态机与错误分类"
fix_ref: "t087"
---
# p088 侧栏偶发「网络连接不可用，系统正在重试」实为非连续失败累计与非网络错误误判

- 现象：2026-11-23 用户实报并附桌面端截图：某 Gmail 账号（截图账号 `ecart95tr@gmail...`）侧栏文件夹树顶部红字「网络连接不可用，系统正在重试」，用户问「为什么总是偶尔出现这个 真的只是偶然吗？」。该文案是 `connectivity_state === 'unreachable'` 的渲染结果（`Sidebar.tsx:196-198`），并非单次网络抖动：需累计至少 5 次被判为传输故障的前台失败且距首次失败≥5 分钟，且中间没有任何成功同步。进入后只有一次成功同步能复位，故表现为「偶尔出现、过一阵自愈」的伪随机。

- 影响：网络与凭据均正常的账号被误标「网络不可达」并红字告警，引发用户误判（p075 已修掉误导性的「请检查账户设置」，但误标本身仍在）；文案宣称「系统正在重试」，在 `sync_enabled=false`（`handlers.py:301-304` 早退）或 IDLE 持有账号（`worker/main.py:234-238` 跳过周期轮询）下成功事件为零，`unreachable` 可长期滞留而并不重试；`Sidebar.tsx:271-277` 仅在 `folders.length === 0` 时渲染健康提示，账号一旦有文件夹则 `invalid` / `unreachable` / `degraded` 全部不可见（p034 遗留盲区）；`queries.ts:69-82` 的 `staleTime=5min` + `refetchOnWindowFocus=false` 使后端恢复后前端最长 5 分钟仍显示红字。已确认同类消费位点：`SettingsModal.tsx:21-33`（筛选/状态标签）、`MessageList.tsx:195/229` 与 `mail/application/queries.py:507-518`（故障账号从汇总排除），共用同一 `connectivity_state` 误标，属同一修复面而非独立缺陷。

- 根因：（产品缺陷，后端状态机与错误分类）

    1. 熔断语义与契约不符：`accounts/health.py:130-142` 的失败计数单调累计、`connectivity_first_failure_at` 只写首次且永不随时间更新，仅成功清零（`record_connectivity_success:81-99`）。`docs/blueprint/conventions.md:160` 要求「连续 5 次失败且跨越 5 分钟窗口」，实际实现是「累计 5 次、任意跨度」。`.scratch/repro_unreachable_intermittent.py` 复现：5 次失败分散在 5 天、中间无成功即升级 `unreachable`。
    2. 非网络错误被判传输故障：`sync/context.py:117-134` 对 `OSError` 一刀切判 `True`（`:121`），并对任意异常文本做 `_TRANSIENT_MARKERS` 宽泛匹配（`:18-31` 含 `connection` / `temporarily` / `ssl` / `eof` 等）；`worker/handlers.py:176-190` 对前台 TRANSPORT 直接调 `record_connectivity_failure`。复现确认：磁盘满 `OSError(ENOSPC)`、句柄耗尽 `OSError(EMFILE)`、配置文案 `DB connection string invalid`、服务端 `service temporarily unavailable` 全部判为 `transport`；而 `transient provider error` 反判 `none`。分类依赖字符串巧合而非结构化语义。
    3. t076 只隔离了 background 传输失败（`context.py:143-158`），未修累计语义与误分类；`docs/tasks/t076_.../review_code.md:124/176/225` 将「状态机可达性张力」标为既定取舍，但「非连续累计」与「非网络错误计入」不属于该取舍，是未被识别的独立缺陷。
    4. 测试把错误语义固化为预期：`tests/mail_core/test_account_health_state_machine.py:214-231` 用手工 `now=20min` 断言跨时段升级，把累计式升级写成正向用例，掩盖「连续」语义丢失。
    5. 与既有条目关系：p075（closed→t076）修的是 background 标记与误导文案，本条是误标与累计的剩余根因；p034（closed→main）记录的有文件夹盲区仍在；均不覆盖本条，故新建而非重开。

- 测试缺口：后端 `test_account_health_state_machine.py:214-231` 只验证跨时段升级、`:127-140/190-211` 仅覆盖 `ConnectionError` / `PermanentAuthError` / `rate_limited` 三个干净样本，缺非网络 `OSError`（ENOSPC/EMFILE/句柄耗尽）、文本含 `connection` 的配置错误、`temporarily unavailable` 的反向断言，也缺 `sync_enabled=false` 时 `unreachable` 不恢复的端到端用例。前端 `Sidebar.test.tsx:1200-1210` 直接 mock `connectivity_state:'unreachable'` 验证文案渲染，不触达后端分类与累计逻辑；无「有文件夹时提示不可见」与「后端恢复但无 SSE 事件时 UI 仍红字」的测试。应补：后端按真实 `backoff_seconds` 序列 + 超窗重置断言「非连续失败不升级」、误分类样本反向断言、暂停账号恢复路径；前端组件层覆盖有/无文件夹两态与陈旧缓存场景，E2E 断言文案与结构化状态一致。

- 修复方向建议（未实施）：熔断改为真正的滑动窗口内连续失败（超窗重置计数或改用带时间窗的队列），与 `conventions.md:160` 的「连续 5 次、跨 5 分钟」对齐；错误分类改为异常类型 + `errno` 白名单，移除对任意异常 `str()` 的宽泛 marker 匹配；为 `unreachable` 增加有界自动复核或让 UI 区分「同步已暂停 / IDLE 持有」与「网络不可达」，使「系统正在重试」文案成立；消除有文件夹时的提示盲区；补齐上述反向与陈旧性测试。

- 线索：`.scratch/repro_unreachable_intermittent.py`（项目 venv 运行：`PYTHONPATH=src .venv/bin/python .scratch/repro_unreachable_intermittent.py`；输出显示 5 天 5 次失败→`unreachable`，ENOSPC/EMFILE/connection string/temporarily unavailable→`transport`）。代码位置：`src/frontend/src/components/Sidebar.tsx:190-203,271-277`、`src/mail_core/accounts/health.py:81-99,102-151`、`src/mail_core/sync/context.py:18-31,117-158`、`src/mail_core/worker/handlers.py:159-190,301-304`、`src/mail_core/worker/main.py:234-238`、`docs/blueprint/conventions.md:160`。本轮只做只读取证与最小复现，未改生产代码。

- 处理：t087；resolution=transferred；reason=已核实非连续累计与非网络错误误判两条根因及全部同类位点，转交 t087 根治状态机与错误分类
