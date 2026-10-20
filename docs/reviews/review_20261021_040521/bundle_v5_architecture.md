> [!NOTE]
> **SUPERSEDED / HISTORICAL REPORT**
> 本报告属于历史审查归档，报告中所列缺陷已在后续版本（截至 da57df7）彻底修复并闭环。

# 视角 5：架构与可维护性

- 范围：HEAD `daca631aec54c30ce02cdb5e6499ae196dc3a72d` 当前全库；按 bundle.json 确定性清单检查模块结构，Python AST 扫描全部生产定义/引用，结合调用链与关联测试复核。非 diff 审阅，当前仍存在问题计入。
- 时间：2026-10-21T04:11:23+08:00。
- 验证：只读 AST、rg、git history；未修改源代码，未执行测试或构建。

## Findings

- [Low][95] mail_core/providers/oauth.py:207 — 两个未使用 OAuth 构造器保留另一套运行配置 — L207-L232 的 `build_gmail_api_transport` / `build_graph_api_transport` 全库无调用、无导出或测试引用；实际生产路径是 factory.py:L20-L36 `_oauth_transport`。两处重复维护 Gmail / Graph base URL，且旧入口默认抛 `HTTP not configured`，生产入口默认接 urllib。后续维护易改错未使用入口。修复：删除无消费者旧构造器，保留 factory 唯一装配入口；若确有仓库外调用约束，先明确公共 API。证据：`rg -n 'build_gmail_api_transport|build_graph_api_transport'` 仅两处定义；上下文 [oauth.py L207-L232](https://github.com/TuTouPower/kkmail/blob/daca631aec54c30ce02cdb5e6499ae196dc3a72d/mail_core/providers/oauth.py#L207-L232)。依据：intensive-review 视角5死代码/重复、AGENTS.md 简洁优先。
- [Low][100] __pycache__/email.cpython-313.pyc:1 — 已删除模块字节码仍由 Git 跟踪 — `git ls-files` 仍包含该二进制，仓库没有对应 email.py；.gitignore 已忽略 `__pycache__/` / `*.py[cod]`，但忽略规则不会解除已有追踪。增加无源可复核生成产物、Python 版本噪声，违反 AGENTS.md 工作区保护中不提交缓存要求。修复：经正常补丁移除这个已跟踪缓存文件，保留忽略规则；当前审阅不删除。定位为二进制第1项，无文本行；通过 `git ls-files __pycache__/email.cpython-313.pyc` 可复核。

## 全量探针与去重边界

- AST 名称引用探针逐一复核：`unwrap`、`request_stop`、`reset_auth_caches`、Alembic upgrade/downgrade、路由函数存在测试/框架/CLI 消费，不作为死代码误报。
- `require_auth_no_csrf` 目前仅定义；`safe_blob_path` 只有测试消费。作为清理观察，不主张为了计数删除可复用安全 API；见测试视角对“测试是否直达生产路径”复核。
- accounts / sync / providers 使用 PEP 562 延迟导出，解决导入环；没有仅凭动态导入/规模判为架构失败。
- API routes -> application/accounts、单一 FastAPI 后端、HTTP transport/CSRF集中、HTML净化入口符合架构方向。
- 未把产品明确排除的发信、联系人、系统通知、扩展或已记录分页/未读badge限制报为缺陷。
- 端到端正文归档、凭据事务、存储卷分裂等跨层断点由正确性/契约视角记录，不在本报告重复计数。

## Traceability

- 规则：AGENTS.md；用户提供全局规则的简洁优先/精准修改/工作区保护；intensive-review §3 视角5。
- 历史：`git log -1 -- mail_core/providers/oauth.py` 指向 `cc8ec27`；当前是全库状态审阅，预存但仍未解决问题保留。
- 附件：bundle.json 与 scope.json 提供确定性范围；测试及无白名单配置作为补充输入。
