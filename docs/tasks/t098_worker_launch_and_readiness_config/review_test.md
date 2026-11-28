# Task review t098（reviewer_focus: 测试）

- task：`t098_worker_launch_and_readiness_config`
- spec：`docs/tasks/t098_worker_launch_and_readiness_config/task.md`
- diff_anchor：`7746212f8d96870d0b7e75fd1868c159993d1a27`
- target：`git diff 7746212f8d96870d0b7e75fd1868c159993d1a27`
- round：1
- reviewed_at：2026-11-29T00:38:00+08:00

reviewed_scope: a3bc3f2b15788107

## Findings

### t098_test_f001 - AC-002「不可读」存活戳无独立用例

- 严重度：minor
- 锚点：AC-002（缺失、不可读、损坏或陈旧的必需戳使 Worker 未就绪）
- 位置：`tests/mail_core/test_t098_worker_launch_readiness.py:217`（`test_ac002_explicit_stamp_gates_readiness_in_standalone_mode`）
- 问题：该用例覆盖了缺失、损坏（写非 JSON）、陈旧（mtime 回拨）与新鲜四态，但未构造「文件存在但不可读」一态；实现侧该态与缺失共用 `read_liveness_stamp` 的 `OSError → None` 分支（`src/mail_core/liveness.py:71-76`），行为已由缺失用例间接覆盖，故仅为覆盖完整性缺口，不影响 AC 判定。
- 建议：补一条以目录路径冒充戳文件（`read_text` 抛 `IsADirectoryError`，跨平台稳定触发 OSError）断言未就绪的用例。

### t098_test_f002 - AC-001 的 /ready 200 只直测 env 模式，CLI 模式靠两段测试组合

- 严重度：minor
- 锚点：AC-001（CLI `--no-worker` 与 env=0 两者在强制门禁下均返回 200）
- 位置：`tests/mail_core/test_t098_worker_launch_readiness.py:195`（`test_ac001_ready_200_for_no_worker_modes_despite_residual_stamp`）与 `:168`（`test_ac001_main_no_worker_publishes_mode_and_starts_no_thread`）
- 问题：/ready 200 用例只设置发布后的 `MAIL_CORE_EMBEDDED_WORKER=0`；CLI 模式由 main() 用例证明「回写 env=0 且探针函数忽略残留戳」后组合推得，组合环节均为真实生产代码（进程入口回写 `os.environ`、探针读同一 env），无 mock 冒充，故组合证据成立、AC 判定不受影响；仅端到端形态上少一条「真跑 main --no-worker 后同进程请求 /ready」的直测。
- 建议：可选补一条组合直测；不补亦可，在测试 docstring 中保留现有组合说明即可。

## 结论

- 改测方向复核：本轮唯一既有测试改动是删除 `tests/mail_core/test_t096_fixes_unit.py` 中未用的 `SimpleNamespace` 导入（spec 范围明列），无断言改动、无迁就实现的改测；其余均为新增测试文件。
- 本轮新发现：2 条（均为 minor）
- 未进表的提示：危险模式扫描已逐项核查——无恒真断言、无删/反转/注释断言、无 `.skip`/`.only`、无 `type: ignore`、无阈值放宽；mock 仅位于系统边界（假 engine 模拟 DB 心跳行、listener 替身、`uvicorn.run` 与 worker `run` 进程边界替身），心跳解析、戳文件读写、路径解析、`/ready` 均为真实生产逻辑与真实文件；`_clean_worker_env` 夹具把默认戳重定向进 `tmp_path` 且逐用例失效探针缓存，隔离断言（默认路径无写入）在 `test_ac003_write_and_read_share_effective_path_and_isolate_default` 中真实校验。reviewer 独立复跑 t098+t096+a294+api_health 套件 34 passed。
- 总体判断：四条 AC 均有真实、可信的测试支撑，断言均为用户可观察行为（线程是否启动、生效 env 回写、`/ready` 状态码与 reason、戳文件实际落点），无假绿；仅存两条 minor 覆盖完整性提示，可 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。`test_ac001_main_no_worker_publishes_mode_and_starts_no_thread` 真跑进程入口断言线程未启动、env 回写为 "0" 且探针忽略残留陈旧戳；`test_ac001_main_env_zero_starts_no_thread` 与默认启动对照、resolver/config 矩阵用例齐全，复跑通过。
- AC-002：TICK-VALID，re_verified。`test_ac002_explicit_stamp_gates_readiness_in_standalone_mode` 覆盖缺失/损坏/陈旧/新鲜四态及新鲜戳不救陈旧心跳，`test_ac002_embedded_mode_requires_stamp` 覆盖内嵌必需戳，`test_ac002_ready_503_when_required_stamp_stale` 经真实 `/ready` 断言 503 与 reason；「不可读」一态仅共用分支间接覆盖，见 t098_test_f001（minor）。
- AC-003：TICK-VALID，re_verified。`test_ac003_stamp_path_priority` 断言默认/数据目录/显式三级优先级，`test_ac003_write_and_read_share_effective_path_and_isolate_default` 以真实文件断言写入落 `tmp_path` 数据目录且共享默认路径不存在，`test_ac003_healthcheck_shares_stamp_resolution` 验证健康检查同源解析，复跑通过。
- AC-004：TICK-VALID，re_verified。`test_ac004_probe_caches_worker_signal_with_short_ttl_and_invalidate` 验证 TTL 内缓存与失效后重读，`test_ac004_ready_rereads_worker_signal_after_failure` 验证就绪失败后下一请求重读恢复 200，`test_ac004_ready_rereads_listener_state_every_call` 验证 LISTEN 断开立即 503，复跑通过。

coverage = 4 / 4

verdict: PASS

## Round 2 (2026-11-29T00:40:22+08:00)

reviewed_scope: 9fe75e57bc375852

## Findings

无（本轮零 finding）。

## 结论

- 前轮 finding 复核：逐条以 diff 为准核实，两条均已真修、闭环——
    - t098_test_f001（AC-002「不可读」存活戳无独立用例）：已消除。`test_ac002_explicit_stamp_gates_readiness_in_standalone_mode` 新增「不可读」一态：把戳文件替换为同名目录（`stamp.unlink()` 后 `stamp.mkdir()`，`tests/mail_core/test_t098_worker_launch_readiness.py:247-253`），断言 `read_worker_active_via_core` 返回未就绪，随后 `stamp.rmdir()` 恢复后续状态——正是 Round 1 建议的跨平台稳定触发 `OSError` 的构造，未换成另一种弱化形式。
    - t098_test_f002（AC-001 的 /ready 200 只直测 env 模式）：已消除。新增 `test_ac001_ready_200_end_to_end_after_cli_no_worker_launch`（`tests/mail_core/test_t098_worker_launch_readiness.py:195-211`）：真跑 `main(["--no-worker"])`（经 `_run_main` 实测线程未启动、env 回写为 "0"），同进程开启强制门禁后请求真实 `/ready`，断言 200、`status == "ready"`、`worker is True`，且残留陈旧默认戳在场——CLI 模式不再靠两段组合推得。
- 改测方向复核：本轮增量仅为新增用例（f001 在既有用例内追加一态、f002 新增一个测试函数），无既有断言改动、无迁就实现的改测；Round 1 记录的唯一既有测试改动（删 `tests/mail_core/test_t096_fixes_unit.py` 未用 `SimpleNamespace` 导入）本轮复核仍在、无回退。
- 本轮新发现：0 条
- 未进表的提示：危险模式扫描本轮重新逐项核查新增测试——无恒真断言、无删/反转/注释断言、无弱化断言、无 `.skip`/`.only`、无 `type: ignore`、无阈值放宽；新增用例的 mock 仍只在系统边界（`uvicorn.run` 与 worker `run` 进程边界替身、假 engine 模拟 DB 心跳行、listener 替身），进程入口、戳文件读写、路径解析、`/ready` 均为真实生产逻辑与真实文件。reviewer 独立复跑 t098+t096+a294+api_health 套件 35 passed（较 Round 1 的 34 条多 1 条，即 f002 新增直测）。
- 总体判断：前轮两条 minor 均已闭环，四条 AC 均有真实、可信的测试支撑，断言均为用户可观察行为，无假绿、无新问题，可 PASS。
- 系统性 follow-up：无

### AC 复验方式

- AC-001：TICK-VALID，re_verified。CLI 模式现由 `test_ac001_ready_200_end_to_end_after_cli_no_worker_launch` 端到端直测（真跑 main --no-worker 后同进程 /ready 返回 200），env 模式由 `test_ac001_main_env_zero_starts_no_thread` 与 `test_ac001_ready_200_for_no_worker_modes_despite_residual_stamp` 覆盖，resolver/config 矩阵齐全，本轮复跑通过。
- AC-002：TICK-VALID，re_verified。`test_ac002_explicit_stamp_gates_readiness_in_standalone_mode` 现覆盖缺失/损坏/不可读（目录冒充戳文件）/陈旧/新鲜五态及新鲜戳不救陈旧心跳，`test_ac002_embedded_mode_requires_stamp` 覆盖内嵌必需戳，`test_ac002_ready_503_when_required_stamp_stale` 经真实 `/ready` 断言 503 与 reason，本轮复跑通过。
- AC-003：TICK-VALID，re_verified。`test_ac003_stamp_path_priority` 断言默认/数据目录/显式三级优先级，`test_ac003_write_and_read_share_effective_path_and_isolate_default` 以真实文件断言写入落 `tmp_path` 数据目录且共享默认路径不存在，`test_ac003_healthcheck_shares_stamp_resolution` 验证健康检查同源解析，本轮复跑通过。
- AC-004：TICK-VALID，re_verified。`test_ac004_probe_caches_worker_signal_with_short_ttl_and_invalidate` 验证 TTL 内缓存与失效后重读，`test_ac004_ready_rereads_worker_signal_after_failure` 验证就绪失败后下一请求重读恢复 200，`test_ac004_ready_rereads_listener_state_every_call` 验证 LISTEN 断开立即 503，本轮复跑通过。

coverage = 4 / 4

verdict: PASS
