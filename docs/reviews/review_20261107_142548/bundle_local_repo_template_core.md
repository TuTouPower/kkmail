# bundle_local_repo_template_core

## responsibilities

- 实现任务工具链核心状态机与工作流引擎（repo_task），管理 task 的生命周期状态（backlog, active, done, dropped）
- 实现跨平台文件锁机制（locks.py），在不同操作系统（Windows msvcrt / POSIX fcntl）下提供线程可重入、进程互斥的排他锁保护
- 提供强一致性不可变事件账本（dispatch_ledger.jsonl）与 exact-identity 尝试控制，杜绝并发冲突与多 agent 竞争
- 实现任务依赖有向无环图调度与冲突分析引擎（scheduling.py, graph.py, plan.py），自动检测依赖环并规划并行链
- 提供健壮的文件事务机制（FileTransaction），在代码与任务文档修改前后提供快照备份与防软链逃逸回滚
- 实现基于标准库 http.server 的本地轻量级任务看板服务端（view_server.py），提供安全令牌鉴权与实时拓扑可视化

## interfaces

- repo_task.locks.file_lock / git_common_lock / control_locked 锁原语
- repo_task.file_transaction.FileTransaction 事务 API
- repo_task.lifecycle.cmd_add / cmd_edit / cmd_finish / cmd_drop 等生命周期命令
- repo_task.control.cmd_view / cmd_effective_status 控制台视图
- repo_task.view_server.serve 看板 HTTP 服务（GET / 与 /task-doc 接口）

## dependencies

- Python 3 标准库（fcntl, msvcrt, threading, http.server, socket, hashlib, subprocess）
- Git CLI（工作区检测、分支解析、对象读取与合并校验）

## flows

- 任务创建流：获取 git common 排他锁 -> 扫描所有 worktree/分支现存编号 -> 计算下一个递增 tid -> 复制 task 模板 -> 写入 front-matter 初始元数据 -> 重建任务索引 -> 失败回滚
- 任务尝试生命周期流：reserve_attempt 记录预留事件 -> claim_execution 声明唯一执行者 owner_id -> running 阶段执行变更 -> attempt_terminal 写入最终状态 -> integrate 确认合并事件
- 看板渲染流：请求附带 session token -> 校验通过 -> 500ms 缓存内复用调度图模型 -> 注入 HTML 模板并转义防 XSS -> 客户端纯 JS 渲染 DAG 与冲突矩阵

## constraints

- 跨进程/跨 worktree 关键操作（取号、状态跃迁、尝试预留）必须持有 git common 目录锁
- 看板服务默认仅监听 loopback 地址（127.0.0.1 / ::1），且每次启动生成随机 16 字节十六进制令牌，无有效 token 拒绝访问
- 文档读取必须严格限制在 docs/tasks 与 docs/archive/tasks 目录下，拒绝软链及路径遍历

## decisions

- 账本采用只增追加（append-only）的 JSONL 格式，不直接原地更新已有状态，保证审计可追溯与崩溃安全
- 前端看板放弃外部框架与 CDN，采用原生 JS/CSS 静态文件与标准库 HTTP 服务单端口托管，杜绝供应链风险与构建依赖
- 文件事务在恢复阶段拷贝备份而非移动消耗，并在恢复失败时保留未竟状态，避免部分恢复导致现场丢失

## evidence

- .repo_template/scripts/repo_task/locks.py:72-139（跨平台文件锁实现、线程可重入与 fork 保护）
- .repo_template/scripts/repo_task/file_transaction.py:67-141（事务 begin/applied/rollback 与软链逃逸防护）
- .repo_template/scripts/repo_task/lifecycle.py:46-82（git_common_lock 保护取号与原子复制）
- .repo_template/scripts/repo_task/scheduling.py:12-41（Tarjan/DFS 依赖环检测算法）
- .repo_template/scripts/repo_task/view_server.py:236-328（严格 CSP、会话 token 验证与 loopback 强制绑定）

## uncertainties

## Findings

No findings.

## views

```json
{
  "security": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "correctness": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "contracts": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "performance": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "design": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "robustness": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "tests": {
    "status": "completed",
    "reviewer": "subagent_ops"
  },
  "documentation": {
    "status": "completed",
    "reviewer": "subagent_ops"
  }
}
```

## files_reviewed

```json
[
  ".repo_template/scripts/repo_task/__init__.py",
  ".repo_template/scripts/repo_task/attempts.py",
  ".repo_template/scripts/repo_task/cli.py",
  ".repo_template/scripts/repo_task/context.py",
  ".repo_template/scripts/repo_task/control.py",
  ".repo_template/scripts/repo_task/documents.py",
  ".repo_template/scripts/repo_task/file_transaction.py",
  ".repo_template/scripts/repo_task/finalization.py",
  ".repo_template/scripts/repo_task/git_ops.py",
  ".repo_template/scripts/repo_task/goal.py",
  ".repo_template/scripts/repo_task/graph.py",
  ".repo_template/scripts/repo_task/integration.py",
  ".repo_template/scripts/repo_task/ledger.py",
  ".repo_template/scripts/repo_task/lifecycle.py",
  ".repo_template/scripts/repo_task/locks.py",
  ".repo_template/scripts/repo_task/monitoring.py",
  ".repo_template/scripts/repo_task/plan.py",
  ".repo_template/scripts/repo_task/recovery.py",
  ".repo_template/scripts/repo_task/review.py",
  ".repo_template/scripts/repo_task/scheduling.py",
  ".repo_template/scripts/repo_task/specs_index.py",
  ".repo_template/scripts/repo_task/store.py",
  ".repo_template/scripts/repo_task/validation.py",
  ".repo_template/scripts/repo_task/view_server.py",
  ".repo_template/scripts/repo_task/view_static/board.css",
  ".repo_template/scripts/repo_task/view_static/board.html",
  ".repo_template/scripts/repo_task/view_static/board.js",
  ".repo_template/scripts/repo_task/view_static/chain_plan.js",
  ".repo_template/scripts/repo_task/worktrees.py"
]
```
